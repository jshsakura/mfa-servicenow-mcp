"""Tests for manage_business_rule (sys_script).

Two behaviours carry most of the weight here, and both exist because a business
rule can fail in a way nothing reports:

1. A rule that saves cleanly and never runs (advanced off with a script, or no
   action_* trigger). The record looks complete in the UI.
2. A rule name identified by name alone. Names repeat across tables BY DESIGN —
   one rule per interface table, all called the same thing — so a name is not an
   identity and picking the first match edits an arbitrary sibling.
"""

import unittest
from unittest.mock import MagicMock, patch

import pytest
from pydantic import ValidationError

from servicenow_mcp.auth.auth_manager import AuthManager
from servicenow_mcp.services import business_rule as br_svc
from servicenow_mcp.tools.business_rule_tools import ManageBusinessRuleParams, manage_business_rule
from servicenow_mcp.tools.sn_api import invalidate_query_cache
from servicenow_mcp.utils.config import AuthConfig, AuthType, BasicAuthConfig, ServerConfig

_TABLE = "x_myapp_gamma"
_OTHER_TABLE = "x_myapp_order_if"


def _config():
    return ServerConfig(
        instance_url="https://test.service-now.com",
        auth=AuthConfig(
            type=AuthType.BASIC,
            basic=BasicAuthConfig(username="alice", password="secret"),
        ),
    )


def _auth():
    auth = MagicMock(spec=AuthManager)
    auth.get_headers.return_value = {"Content-Type": "application/json"}
    return auth


def _record(**over):
    row = {
        "sys_id": "a" * 32,
        "name": "Update Group Count",
        "collection": _TABLE,
        "when": "after",
        "order": "100",
        "active": "true",
        "advanced": "true",
        "action_insert": "true",
        "action_update": "true",
        "action_delete": "false",
    }
    row.update(over)
    return row


def _ok(result):
    resp = MagicMock()
    resp.json.return_value = {"result": result}
    resp.raise_for_status = MagicMock()
    return resp


class TestListAndGet(unittest.TestCase):
    def setUp(self):
        invalidate_query_cache()

    @patch("servicenow_mcp.services.business_rule.sn_query_page")
    def test_filters_build_one_encoded_query(self, page):
        page.return_value = ([_record()], 1)

        result = manage_business_rule(
            _config(),
            _auth(),
            ManageBusinessRuleParams(
                action="list", collection=_TABLE, when="after", active=True, query="Group"
            ),
        )

        assert result["success"] is True
        assert result["count"] == 1
        assert page.call_args.kwargs["query"] == (
            f"collection={_TABLE}^when=after^active=true^nameLIKEGroup"
        )

    @patch("servicenow_mcp.tools.sn_api.sn_count")
    def test_count_only_never_fetches_records(self, count):
        count.return_value = 5

        result = manage_business_rule(
            _config(), _auth(), ManageBusinessRuleParams(action="list", count_only=True)
        )

        assert result == {"success": True, "count": 5, "table": "sys_script"}

    @patch("servicenow_mcp.services.business_rule.sn_query_page")
    def test_get_not_found_says_so(self, page):
        page.return_value = ([], 0)

        result = manage_business_rule(
            _config(), _auth(), ManageBusinessRuleParams(action="get", business_rule_id="Nope")
        )

        assert result["success"] is False
        assert "not found" in result["message"]

    @patch("servicenow_mcp.services.business_rule.sn_query_page")
    def test_an_ambiguous_name_returns_every_candidate_and_picks_none(self, page):
        """The repeated-name case. Editing an arbitrary sibling is the accident."""
        page.return_value = (
            [_record(sys_id="a" * 32), _record(sys_id="b" * 32, collection=_OTHER_TABLE)],
            2,
        )

        result = manage_business_rule(
            _config(),
            _auth(),
            ManageBusinessRuleParams(action="get", business_rule_id="Update Group Count"),
        )

        assert result["success"] is False
        assert "not unique" in result["message"]
        assert [c["collection"] for c in result["candidates"]] == [_TABLE, _OTHER_TABLE]

    @patch("servicenow_mcp.services.business_rule.sn_query_page")
    def test_collection_disambiguates_a_repeated_name(self, page):
        page.return_value = ([_record()], 1)

        manage_business_rule(
            _config(),
            _auth(),
            ManageBusinessRuleParams(
                action="get", business_rule_id="Update Group Count", collection=_TABLE
            ),
        )

        assert page.call_args_list[0].kwargs["query"] == (
            f"name=Update Group Count^collection={_TABLE}"
        )


class TestCreate(unittest.TestCase):
    def setUp(self):
        invalidate_query_cache()

    def test_happy_path_posts_the_expected_body(self):
        auth = _auth()
        auth.make_request.return_value = _ok(
            {"sys_id": "c" * 32, "name": "Update Group Count", "collection": _TABLE}
        )

        result = manage_business_rule(
            _config(),
            auth,
            ManageBusinessRuleParams(
                action="create",
                name="Update Group Count",
                collection=_TABLE,
                when="after",
                script="(function(){})();",
                action_insert=True,
                action_update=True,
            ),
        )

        assert result["success"] is True
        assert result["business_rule_id"] == "c" * 32
        body = auth.make_request.call_args.kwargs["json"]
        assert body["collection"] == _TABLE
        assert body["when"] == "after"
        assert body["action_insert"] == "true"
        assert body["action_delete"] == "false"
        # A script implies an advanced rule — otherwise the script is inert.
        assert body["advanced"] == "true"

    def test_a_script_with_advanced_off_is_refused(self):
        auth = _auth()

        result = manage_business_rule(
            _config(),
            auth,
            ManageBusinessRuleParams(
                action="create",
                name="Inert",
                collection=_TABLE,
                script="gs.info('never runs');",
                advanced=False,
                action_insert=True,
            ),
        )

        assert result["success"] is False
        assert "never executes its script" in result["message"]
        auth.make_request.assert_not_called()

    def test_a_rule_with_no_trigger_is_refused(self):
        auth = _auth()

        result = manage_business_rule(
            _config(),
            auth,
            ManageBusinessRuleParams(
                action="create", name="No trigger", collection=_TABLE, script="x();"
            ),
        )

        assert result["success"] is False
        assert "no trigger is set" in result["message"]
        auth.make_request.assert_not_called()

    def test_a_display_rule_needs_no_dml_trigger(self):
        auth = _auth()
        auth.make_request.return_value = _ok(
            {"sys_id": "d" * 32, "name": "Display", "collection": _TABLE}
        )

        result = manage_business_rule(
            _config(),
            auth,
            ManageBusinessRuleParams(
                action="create",
                name="Display",
                collection=_TABLE,
                when="display",
                script="g_scratchpad.x = 1;",
            ),
        )

        assert result["success"] is True

    def test_a_non_json_response_names_what_came_back(self):
        auth = _auth()
        resp = MagicMock()
        resp.json.return_value = "<html>login</html>"
        resp.raise_for_status = MagicMock()
        auth.make_request.return_value = resp

        result = manage_business_rule(
            _config(),
            auth,
            ManageBusinessRuleParams(
                action="create", name="X", collection=_TABLE, action_insert=True
            ),
        )

        assert result["success"] is False
        assert "re-authenticate" in result["message"]

    def test_name_and_collection_are_required(self):
        with pytest.raises(ValidationError):
            ManageBusinessRuleParams(action="create", name="X")
        with pytest.raises(ValidationError):
            ManageBusinessRuleParams(action="create", collection=_TABLE)


class TestUpdateAndDelete(unittest.TestCase):
    def setUp(self):
        invalidate_query_cache()

    @patch("servicenow_mcp.services.business_rule.sn_query_page")
    def test_update_patches_only_what_changed(self, page):
        page.return_value = ([_record()], 1)
        auth = _auth()
        auth.make_request.return_value = _ok(
            {"sys_id": "a" * 32, "name": "Update Group Count", "collection": _TABLE}
        )

        result = manage_business_rule(
            _config(),
            auth,
            ManageBusinessRuleParams(
                action="update", business_rule_id="a" * 32, script="new();", order=200
            ),
        )

        assert result["success"] is True
        assert auth.make_request.call_args.kwargs["json"] == {"script": "new();", "order": "200"}

    @patch("servicenow_mcp.services.business_rule.sn_query_page")
    def test_an_update_that_would_make_the_rule_inert_is_refused(self, page):
        """Turning every trigger off leaves a rule that exists and does nothing."""
        page.return_value = ([_record()], 1)
        auth = _auth()

        result = manage_business_rule(
            _config(),
            auth,
            ManageBusinessRuleParams(
                action="update",
                business_rule_id="a" * 32,
                action_insert=False,
                action_update=False,
                action_delete=False,
            ),
        )

        assert result["success"] is False
        assert "no trigger is set" in result["message"]
        auth.make_request.assert_not_called()

    @patch("servicenow_mcp.services.business_rule.sn_query_page")
    def test_unmentioned_fields_are_read_from_the_record_not_assumed(self, page):
        # Only `script` changes. The triggers already on the record must keep it
        # reachable — inferring "off" from an absent parameter would refuse a
        # perfectly good edit (and, inverted, would let a real one through).
        page.return_value = ([_record(action_insert="false", action_update="true")], 1)
        auth = _auth()
        auth.make_request.return_value = _ok(
            {"sys_id": "a" * 32, "name": "R", "collection": _TABLE}
        )

        result = manage_business_rule(
            _config(),
            auth,
            ManageBusinessRuleParams(
                action="update", business_rule_id="a" * 32, script="still fine();"
            ),
        )

        assert result["success"] is True

    @patch("servicenow_mcp.services.business_rule.sn_query_page")
    def test_update_of_a_missing_rule_writes_nothing(self, page):
        page.return_value = ([], 0)
        auth = _auth()

        result = manage_business_rule(
            _config(),
            auth,
            ManageBusinessRuleParams(action="update", business_rule_id="ghost", script="x();"),
        )

        assert result["success"] is False
        auth.make_request.assert_not_called()

    def test_update_needs_at_least_one_field(self):
        with pytest.raises(ValidationError):
            ManageBusinessRuleParams(action="update", business_rule_id="a" * 32)

    @patch("servicenow_mcp.services.business_rule.sn_query_page")
    def test_delete_reports_what_it_removed(self, page):
        page.return_value = ([_record()], 1)
        auth = _auth()
        resp = MagicMock()
        resp.raise_for_status = MagicMock()
        auth.make_request.return_value = resp

        result = manage_business_rule(
            _config(),
            auth,
            ManageBusinessRuleParams(action="delete", business_rule_id="a" * 32),
        )

        assert result["success"] is True
        assert result["business_rule_name"] == "Update Group Count"
        assert auth.make_request.call_args[0][0] == "DELETE"

    @patch("servicenow_mcp.services.business_rule.sn_query_page")
    def test_delete_will_not_guess_between_same_named_rules(self, page):
        page.return_value = ([_record(), _record(sys_id="b" * 32, collection=_OTHER_TABLE)], 2)
        auth = _auth()

        result = manage_business_rule(
            _config(),
            auth,
            ManageBusinessRuleParams(action="delete", business_rule_id="Update Group Count"),
        )

        assert result["success"] is False
        auth.make_request.assert_not_called()


class TestReachabilityHelper(unittest.TestCase):
    """The helper directly — it is the one piece both create and update rely on."""

    def test_a_rule_with_a_trigger_and_no_script_is_reachable(self):
        assert (
            br_svc._execution_is_reachable(
                script=None, advanced=False, insert=True, update=False, delete=False, when="before"
            )
            is None
        )

    def test_advanced_off_only_matters_when_there_is_a_script(self):
        assert (
            br_svc._execution_is_reachable(
                script="", advanced=False, insert=True, update=False, delete=False, when="before"
            )
            is None
        )
