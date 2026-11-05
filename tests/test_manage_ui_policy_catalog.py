"""manage_ui_policy: list/get/update/remove_action and kind='catalog'."""

from unittest.mock import MagicMock, patch

import pytest
from pydantic import ValidationError

from servicenow_mcp.tools.ui_policy_tools import ManageUiPolicyParams, manage_ui_policy
from servicenow_mcp.utils.config import AuthConfig, AuthType, BasicAuthConfig, ServerConfig

ITEM = "aaaa1111bbbb2222cccc3333dddd4444"
VSET = "bbbb2222cccc3333dddd4444eeee5555"
VAR_A = "cccc3333dddd4444eeee5555ffff6666"
VAR_B = "dddd4444eeee5555ffff6666aaaa1111"
VAR_SET = "eeee5555ffff6666aaaa1111bbbb2222"
POLICY = "ffff6666aaaa1111bbbb2222cccc3333"
ACTION = "1111aaaa2222bbbb3333cccc4444dddd"

SVC = "servicenow_mcp.services.ui_policy_manage"


def _config():
    return ServerConfig(
        instance_url="https://test.service-now.com",
        auth=AuthConfig(type=AuthType.BASIC, basic=BasicAuthConfig(username="u", password="p")),
    )


def _fake_reads(extra=None, policy=None, action=None):
    """Answer sn_query_page by table. `extra` overrides per table."""
    tables = {
        "item_option_new": lambda q: (
            [{"sys_id": VAR_A, "name": "type_of_refresh"}, {"sys_id": VAR_B, "name": "model"}]
            if q.startswith("cat_item=")
            else [{"sys_id": VAR_SET, "name": "shared_flag"}]
        ),
        "io_set_item": lambda q: [{"variable_set": VSET}],
        "catalog_ui_policy": lambda q: [
            policy
            or {
                "sys_id": POLICY,
                "short_description": "p",
                "catalog_item": ITEM,
                "variable_set": "",
                "catalog_conditions": f"IO:{VAR_A}=single_model^EQ",
            }
        ],
        "catalog_ui_policy_action": lambda q: [
            action
            or {
                "sys_id": ACTION,
                "ui_policy": POLICY,
                "catalog_variable": f"IO:{VAR_A}",
                "visible": "true",
            }
        ],
        **(extra or {}),
    }

    def fake(config, auth, *, table, query, **kw):
        return tables[table](query), None

    return fake


def _auth():
    a = MagicMock()
    resp = MagicMock()
    resp.json.return_value = {"result": {"sys_id": POLICY, "short_description": "p"}}
    a.make_request.return_value = resp
    return a


def call(auth, **kw):
    return manage_ui_policy(_config(), auth, ManageUiPolicyParams(**kw))


class TestValidation:
    def test_catalog_needs_exactly_one_target(self):
        with pytest.raises(ValidationError, match="exactly one"):
            ManageUiPolicyParams(action="create", kind="catalog", short_description="x")
        with pytest.raises(ValidationError, match="exactly one"):
            ManageUiPolicyParams(
                action="create",
                kind="catalog",
                short_description="x",
                catalog_item=ITEM,
                variable_set=VSET,
            )

    def test_cross_kind_field_rejected(self):
        with pytest.raises(ValidationError, match="do not apply"):
            ManageUiPolicyParams(
                action="create", short_description="x", table="incident", catalog_item=ITEM
            )

    def test_tristate_rejects_garbage(self):
        with pytest.raises(ValidationError, match="true, false or ignore"):
            ManageUiPolicyParams(
                action="update_action", kind="catalog", action_id=ACTION, visible="maybe"
            )

    def test_update_action_needs_a_field_and_id(self):
        with pytest.raises(ValidationError, match="action_id"):
            ManageUiPolicyParams(action="remove_action")
        with pytest.raises(ValidationError, match="at least one"):
            ManageUiPolicyParams(action="update_action", action_id=ACTION)

    def test_catalog_add_action_needs_variable(self):
        with pytest.raises(ValidationError, match="variable"):
            ManageUiPolicyParams(action="add_action", kind="catalog", ui_policy=POLICY)


class TestFormUnchanged:
    def test_form_create_still_routes_to_old_service(self):
        with patch("servicenow_mcp.services.ui_policy.create") as m:
            m.return_value = {"success": True}
            call(MagicMock(), action="create", table="incident", short_description="x")
        kw = m.call_args.kwargs
        assert kw["active"] is True and kw["order"] == 100 and kw["on_load"] is True

    def test_form_add_action_bool_becomes_string(self):
        with patch("servicenow_mcp.services.ui_policy.add_action") as m:
            m.return_value = {"success": True}
            call(MagicMock(), action="add_action", ui_policy="p", field="f", visible=False)
        assert m.call_args.kwargs["visible"] == "false"


class TestCatalogCreate:
    def test_name_is_translated_to_io_id(self):
        auth = _auth()
        with patch(f"{SVC}.sn_query_page", side_effect=_fake_reads()):
            out = call(
                auth,
                action="create",
                kind="catalog",
                short_description="show model",
                catalog_item=ITEM,
                catalog_conditions="type_of_refresh=single_model^ORshared_flag=true^EQ",
                applies_req_item=True,
            )
        assert out["success"], out
        body = auth.make_request.call_args.kwargs["json"]
        assert body["catalog_conditions"] == (f"IO:{VAR_A}=single_model^ORIO:{VAR_SET}=true^EQ")
        assert body["catalog_item"] == ITEM and "variable_set" not in body
        assert body["applies_req_item"] == "true"
        assert auth.make_request.call_args.args[0] == "POST"

    def test_unknown_variable_refused_with_candidates(self):
        auth = _auth()
        with patch(f"{SVC}.sn_query_page", side_effect=_fake_reads()):
            out = call(
                auth,
                action="create",
                kind="catalog",
                short_description="x",
                catalog_item=ITEM,
                catalog_conditions="nope=1",
            )
        assert out["success"] is False
        assert "unknown variable 'nope'" in out["message"] and "type_of_refresh" in out["message"]
        auth.make_request.assert_not_called()

    def test_ambiguous_name_refused(self):
        dup = {
            "item_option_new": lambda q: [
                {"sys_id": VAR_A, "name": "model"},
                {"sys_id": VAR_B, "name": "model"},
            ],
            "io_set_item": lambda q: [],
        }
        auth = _auth()
        with patch(f"{SVC}.sn_query_page", side_effect=_fake_reads(dup)):
            out = call(
                auth,
                action="create",
                kind="catalog",
                short_description="x",
                catalog_item=ITEM,
                catalog_conditions="model=1",
            )
        assert out["success"] is False and "ambiguous" in out["message"]
        assert VAR_A in out["message"] and VAR_B in out["message"]


class TestCatalogAction:
    def test_add_action_writes_io_reference(self):
        auth = _auth()
        with patch(f"{SVC}.sn_query_page", side_effect=_fake_reads()):
            out = call(
                auth,
                action="add_action",
                kind="catalog",
                ui_policy=POLICY,
                variable="model",
                visible=True,
                mandatory="ignore",
            )
        assert out["success"], out
        body = auth.make_request.call_args.kwargs["json"]
        assert body["catalog_variable"] == f"IO:{VAR_B}"
        assert (body["visible"], body["mandatory"]) == ("true", "ignore")
        assert body["catalog_item"] == ITEM

    def test_add_action_unknown_variable_refused(self):
        auth = _auth()
        with patch(f"{SVC}.sn_query_page", side_effect=_fake_reads()):
            out = call(auth, action="add_action", kind="catalog", ui_policy=POLICY, variable="zzz")
        assert out["success"] is False and "unknown variable" in out["message"]
        auth.make_request.assert_not_called()


class TestDryRunMakesNoWrite:
    def test_update_dry_run(self):
        auth = _auth()
        with (
            patch(f"{SVC}.sn_query_page", side_effect=_fake_reads()),
            patch(
                "servicenow_mcp.tools._preview._fetch_target",
                return_value={"sys_id": POLICY, "active": "true"},
            ),
        ):
            out = call(
                auth, action="update", kind="catalog", ui_policy=POLICY, active=False, dry_run=True
            )
        assert out["dry_run"] is True and "active" in out["proposed_changes"]
        auth.make_request.assert_not_called()

    def test_update_action_dry_run(self):
        auth = _auth()
        with (
            patch(f"{SVC}.sn_query_page", side_effect=_fake_reads()),
            patch(
                "servicenow_mcp.tools._preview._fetch_target",
                return_value={"sys_id": ACTION, "visible": "true"},
            ),
        ):
            out = call(
                auth,
                action="update_action",
                kind="catalog",
                action_id=ACTION,
                visible=False,
                dry_run=True,
            )
        assert out["dry_run"] is True
        auth.make_request.assert_not_called()

    def test_remove_action_dry_run_then_real_delete(self):
        auth = _auth()
        with (
            patch(f"{SVC}.sn_query_page", side_effect=_fake_reads()),
            patch("servicenow_mcp.tools._preview._fetch_target", return_value={"sys_id": ACTION}),
        ):
            out = call(auth, action="remove_action", kind="catalog", action_id=ACTION, dry_run=True)
            assert out["dry_run"] is True and out["operation"] == "delete"
            auth.make_request.assert_not_called()
            out = call(auth, action="remove_action", kind="catalog", action_id=ACTION)
        assert out["success"], out
        (method, url), _ = auth.make_request.call_args
        assert method == "DELETE" and url.endswith(f"/catalog_ui_policy_action/{ACTION}")


class TestGet:
    def test_conditions_readable_and_variable_name(self):
        with patch(f"{SVC}.sn_query_page", side_effect=_fake_reads()):
            out = call(MagicMock(), action="get", kind="catalog", ui_policy=POLICY)
        assert out["success"], out
        assert out["policy"]["conditions_readable"] == "type_of_refresh=single_model^EQ"
        assert out["actions"][0]["variable_name"] == "type_of_refresh"

    def test_not_found(self):
        with patch(
            f"{SVC}.sn_query_page", side_effect=_fake_reads({"catalog_ui_policy": lambda q: []})
        ):
            out = call(MagicMock(), action="get", kind="catalog", ui_policy=POLICY)
        assert out["success"] is False and "not found" in out["message"]

    def test_list_count_only(self):
        with patch(f"{SVC}.sn_query_page", return_value=([], 7)):
            out = call(MagicMock(), action="list", kind="catalog", count_only=True)
        assert out["count"] == 7


class TestProtection:
    def test_protected_policy_refused(self):
        pol = {"sys_id": POLICY, "catalog_item": ITEM, "sys_policy": "read"}
        auth = _auth()
        with patch(f"{SVC}.sn_query_page", side_effect=_fake_reads(policy=pol)):
            out = call(auth, action="update", kind="catalog", ui_policy=POLICY, active=False)
        assert out["success"] is False and "protected" in out["message"]
        auth.make_request.assert_not_called()

    def test_non_customer_package_refused(self):
        pol = {"sys_id": POLICY, "catalog_item": ITEM, "sys_package": VAR_SET}
        reads = _fake_reads(
            {"sys_package": lambda q: [{"name": "Service Catalog", "source": "com.glide.catalog"}]},
            policy=pol,
        )
        auth = _auth()
        with patch(f"{SVC}.sn_query_page", side_effect=reads):
            out = call(auth, action="update", kind="catalog", ui_policy=POLICY, active=False)
        assert out["success"] is False and "non-customer package" in out["message"]
        auth.make_request.assert_not_called()

    def test_protected_action_not_removed(self):
        act = {"sys_id": ACTION, "ui_policy": POLICY, "sys_policy": "protected"}
        auth = _auth()
        with patch(f"{SVC}.sn_query_page", side_effect=_fake_reads(action=act)):
            out = call(auth, action="remove_action", kind="catalog", action_id=ACTION)
        assert out["success"] is False and "protected" in out["message"]
        auth.make_request.assert_not_called()

    def test_customer_scope_package_allowed(self):
        pol = {"sys_id": POLICY, "catalog_item": ITEM, "sys_package": VAR_SET}
        reads = _fake_reads(
            {"sys_package": lambda q: [{"name": "My App", "source": "x_myapp"}]}, policy=pol
        )
        auth = _auth()
        with patch(f"{SVC}.sn_query_page", side_effect=reads):
            out = call(auth, action="update", kind="catalog", ui_policy=POLICY, active=False)
        assert out["success"], out
