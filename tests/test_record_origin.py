"""Who delivered a record — the package verdict (utils/record_origin.py)."""

from unittest.mock import MagicMock, patch

import pytest

from servicenow_mcp.utils import record_origin as ro

pytestmark = pytest.mark.real_record_origin


@pytest.mark.parametrize(
    "row,verdict",
    [
        # Service Portal - Core: a platform plugin.
        ({"sys_package": "aaaa1111", "sys_package.sys_class_name": "sys_plugins"}, ro.SERVICENOW),
        # Employee Center: a store app whose scope vendor is ServiceNow.
        (
            {
                "sys_package": "bbbb2222",
                "sys_package.sys_class_name": "sys_store_app",
                "sys_scope.vendor": "ServiceNow",
            },
            ro.SERVICENOW,
        ),
        (
            {
                "sys_package": "cccc3333",
                "sys_package.sys_class_name": "sys_store_app",
                "sys_scope.vendor": "Acme Partner",
            },
            ro.VENDOR,
        ),
        # Built on this instance.
        ({"sys_package": "dddd4444", "sys_package.sys_class_name": "sys_app"}, ro.CUSTOMER),
        # Created in global by the customer: the Global package (class sys_scope).
        ({"sys_package": "global", "sys_package.sys_class_name": "sys_scope"}, ro.CUSTOMER),
    ],
)
def test_the_package_decides_who_delivered_a_record(row, verdict):
    assert ro.classify(row)["verdict"] == verdict


@pytest.mark.parametrize(
    "row",
    [
        {},  # package fields never came back (unknown field, ACL)
        {"sys_package": "eeee5555", "sys_package.sys_class_name": "sys_store_app"},  # no vendor
        {"sys_package": "ffff6666", "sys_package.sys_class_name": "something_new"},
    ],
)
def test_what_could_not_be_read_is_undetermined_never_customer(row):
    out = ro.classify(row)
    assert out["verdict"] == ro.UNDETERMINED
    assert out["reason"]


def test_the_servicenow_boolean_on_sp_widget_is_not_the_signal():
    """Measured: Employee Center widgets carry servicenow=false."""
    row = {
        "servicenow": "false",
        "sys_package": "bbbb2222",
        "sys_package.sys_class_name": "sys_store_app",
        "sys_scope.vendor": "ServiceNow",
    }
    assert ro.classify(row)["verdict"] == ro.SERVICENOW


def test_a_failed_read_is_undetermined_with_the_reason():
    with patch("servicenow_mcp.tools.sn_api.sn_query_page", side_effect=RuntimeError("boom")):
        out = ro.record_origin(
            MagicMock(), MagicMock(), "sp_widget", "aaaa1111bbbb2222cccc3333dddd4444"
        )
    assert out["verdict"] == ro.UNDETERMINED
    assert "boom" in out["reason"]


def test_a_login_failure_is_not_turned_into_a_verdict():
    with patch(
        "servicenow_mcp.tools.sn_api.sn_query_page",
        side_effect=ValueError("LOGIN_CANCELLED_BY_USER (x): timed out"),
    ):
        with pytest.raises(ValueError, match="LOGIN_CANCELLED_BY_USER"):
            ro.record_origin(
                MagicMock(), MagicMock(), "sp_widget", "aaaa1111bbbb2222cccc3333dddd4444"
            )


def test_the_live_read_asks_for_the_package_fields():
    with patch(
        "servicenow_mcp.tools.sn_api.sn_query_page",
        return_value=([{"sys_package": "global", "sys_package.sys_class_name": "sys_scope"}], 1),
    ) as q:
        out = ro.record_origin(
            MagicMock(), MagicMock(), "sp_widget", "aaaa1111bbbb2222cccc3333dddd4444"
        )
    assert out["verdict"] == ro.CUSTOMER
    fields = q.call_args.kwargs["fields"].split(",")
    assert {"sys_package.sys_class_name", "sys_scope.vendor", "sys_class_name"} <= set(fields)


def test_clone_follows_the_record_class_not_the_folder():
    assert "clone_header_footer" in ro.clone_call("sp_header_footer", "aaaa1111", "hdr")
    assert "clone_widget" in ro.clone_call("sp_widget", "aaaa1111", "w")
    assert ro.clone_call("sys_script_include", "aaaa1111", "si") is None


def test_a_clone_id_built_from_a_display_name_is_a_slug():
    call = ro.clone_call("sp_widget", "aaaa1111bbbb2222cccc3333dddd4444", "KB Categories - KBv3")
    assert "new_id='kb-categories-kbv3-custom'" in call
