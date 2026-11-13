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


# --- created inside a ServiceNow store app's scope (_born_here) -------------

_STORE_ROW = {
    "sys_id": "aaaa1111bbbb2222cccc3333dddd0301",
    "sys_package": "bbbb2222",
    "sys_package.sys_class_name": "sys_store_app",
    "sys_scope.vendor": "ServiceNow",
    "sys_update_name": "sp_widget_aaaa1111bbbb2222cccc3333dddd0301",
    "sys_created_on": "2026-11-12 01:04:10",
    "sys_created_by": "alice",
}


def _origin_with(versions, row=None):
    """record_origin over a record read and a version read, in that order."""
    reads = [([dict(row or _STORE_ROW)], 1)]
    reads.append(versions if isinstance(versions, Exception) else (versions, len(versions)))
    with patch("servicenow_mcp.tools.sn_api.sn_query_page", side_effect=reads) as q:
        out = ro.record_origin(MagicMock(), MagicMock(), "sp_widget", _STORE_ROW["sys_id"])
    return out, q


def _version(at, by="alice", source="sys_update_set"):
    return {"sys_created_on": at, "sys_created_by": by, "source_table": source}


def test_a_record_created_here_in_a_store_scope_is_the_customers():
    out, q = _origin_with([_version("2026-11-12 01:04:12"), _version("2026-11-12 03:00:00")])
    assert out["verdict"] == ro.CUSTOMER
    assert "created on this instance by alice" in out["created_in_vendor_scope"]
    version_read = q.call_args_list[1].kwargs
    assert version_read["table"] == "sys_update_version"
    assert version_read["query"].startswith("name=sp_widget_aaaa1111bbbb2222cccc3333dddd0301")


@pytest.mark.parametrize(
    "versions,why",
    [
        # An untouched baseline record: no history. NOT the customer signal.
        ([], "no version history"),
        # Customer edited a delivered record long after it was created.
        ([_version("2026-11-13 09:00:00")], "no local version at creation"),
        # Moved in by an update set committed later: the source's creation date.
        ([_version("2026-11-12 05:00:00", source="sys_remote_update_set")], "no local version"),
        # A version at creation, but by someone else (an install, then an edit).
        ([_version("2026-11-12 01:04:20", by="bob")], "no local version at creation"),
        # Written at creation but not through a local update set.
        ([_version("2026-11-12 01:04:11", source="sys_upgrade_history")], "no local version"),
        # A version BEFORE the record existed proves nothing about its birth.
        ([_version("2026-11-12 01:03:00")], "no local version at creation"),
    ],
)
def test_without_proof_of_birth_here_a_store_app_record_stays_servicenows(versions, why):
    out, _ = _origin_with(versions)
    assert out["verdict"] == ro.SERVICENOW
    assert why in out["delivery_basis"]


def test_an_unreadable_history_keeps_the_gate_and_says_why():
    out, _ = _origin_with(RuntimeError("acl"))
    assert out["verdict"] == ro.SERVICENOW
    assert "version history not readable: acl" in out["delivery_basis"]


def test_a_capped_history_says_it_was_capped():
    out, _ = _origin_with([_version("2026-11-13 09:00:00")] * ro._VERSION_PAGE)
    assert out["verdict"] == ro.SERVICENOW
    assert "history is longer" in out["delivery_basis"]


def test_a_missing_creation_stamp_is_not_proof():
    row = dict(_STORE_ROW, sys_created_on="")
    with patch("servicenow_mcp.tools.sn_api.sn_query_page", return_value=([row], 1)) as q:
        out = ro.record_origin(MagicMock(), MagicMock(), "sp_widget", row["sys_id"])
    assert out["verdict"] == ro.SERVICENOW
    assert q.call_count == 1  # nothing to compare against, so no history read


def test_a_plugin_record_is_never_asked():
    row = {"sys_package": "aaaa1111", "sys_package.sys_class_name": "sys_plugins"}
    with patch("servicenow_mcp.tools.sn_api.sn_query_page", return_value=([row], 1)) as q:
        out = ro.record_origin(
            MagicMock(), MagicMock(), "sp_widget", "aaaa1111bbbb2222cccc3333dddd4444"
        )
    assert out["verdict"] == ro.SERVICENOW
    assert q.call_count == 1


def test_a_login_failure_on_the_history_read_is_raised():
    with pytest.raises(ValueError, match="LOGIN_CANCELLED_BY_USER"):
        _origin_with(ValueError("LOGIN_CANCELLED_BY_USER (x): timed out"))
