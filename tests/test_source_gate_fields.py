"""A downloaded record must carry what STOPS it from running, not only its code.

The local tree used to hold a business rule's `script` and `condition` and
nothing else. Everything that decides whether that script is ever reached —
the Filter Condition, the role gate, the per-DML action checkboxes, the
'Set field values' template — stayed on the server. So a rule that a filter
excluded from every record read, on disk, exactly like one that fires on every
write: same files, same bytes, no marker anywhere. The code was right and the
conclusion drawn from it was wrong, which is the worst failure this repo has —
an absence rendered as evidence of safety.

These tests pin the fields to the download spec, the on-disk names to the
canonical layout, the push map that follows from both, and the audit's refusal
to print an execution sequence it did not read.
"""

import json
from unittest.mock import MagicMock, patch

import pytest

from servicenow_mcp.tools.source_audit_tools import (
    _build_execution_order,
    _gate_cell,
    _order_cell,
    _order_sort_key,
    _scan_source_index,
)
from servicenow_mcp.tools.source_tools import SOURCE_CONFIG, _download_source_types
from servicenow_mcp.tools.sync_tools import _folder_layout_field_map
from servicenow_mcp.utils.config import AuthConfig, AuthType, BasicAuthConfig, ServerConfig
from servicenow_mcp.utils.source_layout import field_filename

# A rule that is active, correct, and fires on nothing.
_FILTER = "state=3^assigned_toISEMPTY^priority<3"


@pytest.fixture()
def config() -> ServerConfig:
    return ServerConfig(
        instance_url="https://test.service-now.com",
        auth=AuthConfig(
            type=AuthType.BASIC,
            basic=BasicAuthConfig(username="admin", password="password"),
        ),
    )


@pytest.fixture()
def auth() -> MagicMock:
    return MagicMock()


def _br_record(**overrides):
    record = {
        "sys_id": "br-1",
        "name": "Set defaults",
        "collection": "x_app_request",
        "when": "before",
        "order": "100",
        "active": "true",
        "advanced": "true",
        "action_insert": "true",
        "action_update": "false",
        "action_delete": "false",
        "action_query": "false",
        "role_conditions": "",
        "template": "",
        "abort_action": "false",
        "add_message": "false",
        "sys_scope": "x_app",
        "sys_updated_on": "2026-04-01 14:00:00",
        "sys_updated_by": "alice",
        "sys_mod_count": "4",
        "script": "(function executeRule(current, previous) {\n  current.u_flag = true;\n})();",
        "condition": "",
        "filter_condition": _FILTER,
    }
    record.update(overrides)
    return record


def _run_download(config, auth, scope_root, tmp_path, records, page_side_effect=None):
    with (
        patch("servicenow_mcp.tools.source_tools.sn_query_all") as q_all,
        patch("servicenow_mcp.tools.source_tools.sn_query_page") as q_page,
    ):
        q_all.return_value = records
        q_page.side_effect = page_side_effect or (lambda *a, **k: ([], None))
        result = _download_source_types(
            config,
            auth,
            scope="x_app",
            source_types=["business_rule"],
            scope_root=scope_root,
            root=tmp_path,
        )
    return result, q_page


# ---------------------------------------------------------------------------
# The download spec
# ---------------------------------------------------------------------------


class TestGateFieldsAreDownloaded:
    def test_business_rule_fetches_its_filter_condition(self):
        """The field the whole class of bug is named after."""
        assert "filter_condition" in SOURCE_CONFIG["business_rule"]["source_fields"]

    @pytest.mark.parametrize(
        "source_type,field",
        [
            # Gates, per family. Each one can make an active record a no-op.
            ("business_rule", "role_conditions"),
            ("business_rule", "action_insert"),
            ("business_rule", "action_update"),
            ("business_rule", "action_delete"),
            ("business_rule", "action_query"),
            # 'Set field values' — the rule mutates records with no script.
            ("business_rule", "template"),
            ("business_rule", "order"),
            ("client_script", "field"),
            ("client_script", "order"),
            ("ui_action", "onclick"),
            ("ui_action", "order"),
            ("acl", "admin_overrides"),
        ],
    )
    def test_family_records_what_gates_it(self, source_type, field):
        assert field in SOURCE_CONFIG[source_type]["summary_fields"], (source_type, field)

    @pytest.mark.parametrize(
        "source_type,field",
        [
            ("business_rule", "filter_condition"),
            ("client_script", "condition"),
            ("ui_action", "condition"),
            # A whole second script body, not a detail.
            ("ui_action", "client_script_v2"),
            # Most ACLs decide on `condition` and have no script at all.
            ("acl", "condition"),
        ],
    )
    def test_gate_bodies_are_source_fields_not_metadata(self, source_type, field):
        """Source fields get a file, a content sha, a diff and a push.

        Metadata gets none of those. A gate that decides whether code runs is
        edited like code, so it has to be diffable and pushable like code.
        """
        assert field in SOURCE_CONFIG[source_type]["source_fields"], (source_type, field)


class TestGateFilesRoundTrip:
    @pytest.mark.parametrize(
        "field,filename",
        [
            ("filter_condition", "filter_condition.txt"),
            ("client_script_v2", "client_script_v2.js"),
            ("condition", "condition.js"),
        ],
    )
    def test_canonical_filename(self, field, filename):
        assert field_filename(field) == filename

    def test_filter_condition_is_not_named_like_a_script(self):
        """An encoded query is not JavaScript. A .js name aims every code
        scanner in the repo at it as if it were."""
        assert not field_filename("filter_condition").endswith(".js")

    @pytest.mark.parametrize(
        "table,filename,field",
        [
            ("sys_script", "filter_condition.txt", "filter_condition"),
            ("sys_script_client", "condition.js", "condition"),
            ("sys_ui_action", "client_script_v2.js", "client_script_v2"),
            ("sys_security_acl", "condition.js", "condition"),
        ],
    )
    def test_downloaded_gate_is_pushable_by_path(self, table, filename, field):
        """diff/push derive their map from SOURCE_CONFIG, so a field that can be
        downloaded and edited must resolve back to its column — a file the
        uploader cannot place is an edit that silently never lands."""
        assert (_folder_layout_field_map(table) or {}).get(filename) == field


# ---------------------------------------------------------------------------
# What actually reaches disk
# ---------------------------------------------------------------------------


class TestDownloadWritesGates:
    def test_filter_condition_lands_next_to_the_script(self, config, auth, tmp_path):
        scope_root = tmp_path / "test" / "x_app"
        scope_root.mkdir(parents=True)

        _run_download(config, auth, scope_root, tmp_path, [_br_record()])

        rec = scope_root / "sys_script" / "x_app_request" / "Set_defaults"
        assert (rec / "script.js").exists()
        assert (rec / "filter_condition.txt").read_text() == _FILTER

    def test_metadata_carries_the_action_checkboxes(self, config, auth, tmp_path):
        scope_root = tmp_path / "test" / "x_app"
        scope_root.mkdir(parents=True)

        _run_download(config, auth, scope_root, tmp_path, [_br_record()])

        rec = scope_root / "sys_script" / "x_app_request" / "Set_defaults"
        meta = json.loads((rec / "_metadata.json").read_text())
        assert meta["action_insert"] == "true"
        # The script says nothing about this; the checkbox is the whole answer.
        assert meta["action_update"] == "false"
        assert meta["order"] == "100"

    def test_gate_is_anchored_so_a_local_edit_can_be_pushed(self, config, auth, tmp_path):
        """No sha, no anchor; no anchor, the push gate refuses the file."""
        scope_root = tmp_path / "test" / "x_app"
        scope_root.mkdir(parents=True)

        _run_download(config, auth, scope_root, tmp_path, [_br_record()])

        sync_meta = json.loads((scope_root / "sys_script" / "_sync_meta.json").read_text())
        entry = next(iter(sync_meta.values()))
        assert "filter_condition" in entry["field_shas"]


class TestBlankGateDoesNotCostARoundTrip:
    """A field that is blank on purpose must not be re-asked every download.

    Most rules have no filter condition and most UI actions have no Workspace
    script. Treating every such blank as a possibly-truncated read turns "the
    family gained a field" into one extra HTTP call per record, forever.
    """

    def _seed(self, config, auth, tmp_path, record):
        scope_root = tmp_path / "test" / "x_app"
        scope_root.mkdir(parents=True)
        _run_download(config, auth, scope_root, tmp_path, [record])
        return scope_root

    def test_anchored_record_with_no_filter_is_not_refetched(self, config, auth, tmp_path):
        blank = _br_record(filter_condition="")
        scope_root = self._seed(config, auth, tmp_path, blank)

        # Second download: the record is on disk and anchored, filter still blank.
        _, q_page = _run_download(config, auth, scope_root, tmp_path, [blank])

        assert q_page.call_count == 0, "a legitimately blank gate triggered a per-record fetch"

    def test_a_gate_that_vanished_from_the_batch_read_is_refetched(self, config, auth, tmp_path):
        """The opposite case: content WAS there, now the bulk body reads blank.

        That is the spurious-blank the retry exists for, and it must still fire —
        losing a gate is exactly as bad as never fetching one.
        """
        scope_root = self._seed(config, auth, tmp_path, _br_record())
        rec = scope_root / "sys_script" / "x_app_request" / "Set_defaults"
        (rec / "filter_condition.txt").unlink()  # prior download's file lost

        moved = _br_record(
            filter_condition="", sys_updated_on="2026-05-01 09:00:00", sys_mod_count="5"
        )
        _, q_page = _run_download(
            config,
            auth,
            scope_root,
            tmp_path,
            [moved],
            page_side_effect=lambda *a, **k: ([{"filter_condition": _FILTER}], None),
        )

        assert q_page.call_count == 1
        assert (rec / "filter_condition.txt").read_text() == _FILTER


# ---------------------------------------------------------------------------
# The audit must not print a sequence it did not read
# ---------------------------------------------------------------------------


class TestExecutionOrderTellsTheTruth:
    def test_order_sorts_numerically(self):
        """The order column is an integer held as a string: sorted as text,
        "100" comes before "9" — the exact inversion the report exists to show."""
        items = [{"order": "100", "order_read": True}, {"order": "9", "order_read": True}]
        assert sorted(items, key=_order_sort_key)[0]["order"] == "9"

    def test_unread_order_sorts_last_never_as_zero(self):
        known = {"order": "100", "order_read": True, "has_order": True}
        unread = {"order": "", "order_read": False, "has_order": True}
        assert sorted([unread, known], key=_order_sort_key)[0] is known

    @pytest.mark.parametrize(
        "item,expected",
        [
            ({"order": "100", "has_order": True, "order_read": True}, "100"),
            # No order column at all (ACLs) — not applicable.
            ({"order": "", "has_order": False, "order_read": False}, "—"),
            # Tree predates gate capture — unknown, not zero.
            ({"order": "", "has_order": True, "order_read": False}, "?"),
            # Asked the server; it really is empty.
            ({"order": "", "has_order": True, "order_read": True}, "(empty)"),
        ],
    )
    def test_blank_order_says_which_kind_of_blank(self, item, expected):
        assert _order_cell(item) == expected

    def test_gate_cell_shows_the_condition_instead_of_always(self):
        cell = _gate_cell({"has_order": True, "order_read": True, "filter_condition": _FILTER})
        assert "always" not in cell
        # Escaped: `priority<3` interpolated raw eats the rest of the row.
        assert "priority&lt;3" in cell

    def test_ungated_record_says_always(self):
        assert _gate_cell({"has_order": True, "order_read": True}) == "always"

    def test_legacy_tree_refuses_to_claim_always(self):
        """The reassuring branch is the one that needs the guard: a tree whose
        download never asked for the gate fields knows nothing about them."""
        cell = _gate_cell({"has_order": True, "order_read": False})
        assert "always" not in cell
        assert "not captured" in cell


class TestAuditReadsTheGateFromTheTree:
    def _tree(self, tmp_path, *, filter_condition):
        rec = tmp_path / "x_app" / "sys_script" / "x_app_request" / "Set_defaults"
        rec.mkdir(parents=True)
        (rec / "_metadata.json").write_text(
            json.dumps(
                {
                    "source_type": "business_rule",
                    "table": "sys_script",
                    "source_table": "sys_script",
                    "sys_id": "br-1",
                    "name": "Set defaults",
                    "collection": "x_app_request",
                    "when": "before",
                    "order": "100",
                    "active": "true",
                }
            )
        )
        (rec / "script.js").write_text("// body\n")
        if filter_condition:
            (rec / "filter_condition.txt").write_text(filter_condition)
        return tmp_path / "x_app"

    def test_gated_rule_is_marked_gated(self, tmp_path):
        index = _scan_source_index(self._tree(tmp_path, filter_condition=_FILTER))
        br = next(e for e in index if e["source_type"] == "business_rule")
        assert br["filter_condition"] == _FILTER

        item = _build_execution_order(index)["x_app_request"]["business_rules"][0]
        assert item["conditional"] is True

    def test_ungated_rule_is_not(self, tmp_path):
        index = _scan_source_index(self._tree(tmp_path, filter_condition=""))
        item = _build_execution_order(index)["x_app_request"]["business_rules"][0]
        assert item["conditional"] is False
        assert item["order_read"] is True


# ---------------------------------------------------------------------------
# Gates that do not live on the record
# ---------------------------------------------------------------------------


def _acl_record(**overrides):
    record = {
        "sys_id": "acl-1",
        "name": "x_app_request.watch_list",
        "type": "record",
        "operation": "write",
        "active": "true",
        "admin_overrides": "false",
        "advanced": "false",
        "sys_scope": "x_app",
        "sys_updated_on": "2026-04-01 14:00:00",
        "sys_updated_by": "alice",
        "sys_mod_count": "2",
        # The common shape: no script at all, the whole decision is elsewhere.
        "script": "",
        "condition": "active=true^EQ",
    }
    record.update(overrides)
    return record


def _run_acl_download(config, auth, scope_root, tmp_path, records, m2m_rows, m2m_exc=None):
    def _all(*args, **kwargs):
        if kwargs.get("table") == "sys_security_acl_role":
            if m2m_exc:
                raise m2m_exc
            return m2m_rows
        return records

    with (
        patch("servicenow_mcp.tools.source_tools.sn_query_all", side_effect=_all),
        patch("servicenow_mcp.tools.source_tools.sn_query_page", return_value=([], None)),
    ):
        return _download_source_types(
            config,
            auth,
            scope="x_app",
            source_types=["acl"],
            scope_root=scope_root,
            root=tmp_path,
            skip_empty_source_retry={"acl"},
        )


class TestAclRolesAreCaptured:
    """An ACL's required roles are rows in sys_security_acl_role, not a column.

    That shape is why they used to be dropped — and an ACL that demands `admin`
    landed on disk identical to one that demands nothing.
    """

    def _meta(self, scope_root):
        rec = scope_root / "sys_security_acl" / "x_app_request.watch_list"
        return json.loads((rec / "_metadata.json").read_text())

    def test_roles_land_in_metadata_as_names(self, config, auth, tmp_path):
        scope_root = tmp_path / "test" / "x_app"
        scope_root.mkdir(parents=True)

        _run_acl_download(
            config,
            auth,
            scope_root,
            tmp_path,
            [_acl_record()],
            [
                {"sys_security_acl": "acl-1", "sys_user_role.name": "itil"},
                {"sys_security_acl": "acl-1", "sys_user_role.name": "admin"},
            ],
        )

        meta = self._meta(scope_root)
        # Names, not sys_ids: a role sys_id differs per instance.
        assert meta["roles"] == "admin, itil"
        assert meta["roles_known"] == "true"

    def test_an_acl_with_no_roles_says_so_only_when_the_read_completed(
        self, config, auth, tmp_path
    ):
        scope_root = tmp_path / "test" / "x_app"
        scope_root.mkdir(parents=True)

        _run_acl_download(config, auth, scope_root, tmp_path, [_acl_record()], [])

        meta = self._meta(scope_root)
        assert meta["roles"] == ""
        assert meta["roles_known"] == "true"

    def test_a_failed_m2m_read_is_never_reported_as_no_roles(self, config, auth, tmp_path):
        """The whole reason `roles_known` exists. A blank `roles` written after a
        failed read is the reassuring answer to a question nobody asked."""
        scope_root = tmp_path / "test" / "x_app"
        scope_root.mkdir(parents=True)

        _run_acl_download(
            config,
            auth,
            scope_root,
            tmp_path,
            [_acl_record()],
            [],
            m2m_exc=RuntimeError("403"),
        )

        meta = self._meta(scope_root)
        assert meta["roles_known"] == "false"
        assert "roles" not in meta

    def test_audit_shows_the_role_gate(self, config, auth, tmp_path):
        scope_root = tmp_path / "test" / "x_app"
        scope_root.mkdir(parents=True)
        _run_acl_download(
            config,
            auth,
            scope_root,
            tmp_path,
            [_acl_record()],
            [{"sys_security_acl": "acl-1", "sys_user_role.name": "itil"}],
        )

        index = _scan_source_index(scope_root)
        acl = next(e for e in index if e["source_type"] == "acl")
        assert acl["roles"] == "itil"

        cell = _gate_cell({"roles": acl["roles"], "roles_known": "true"})
        assert "itil" in cell
        assert "always" not in cell

    def test_unread_roles_do_not_render_as_always(self):
        cell = _gate_cell({"roles": "", "roles_known": "false"})
        assert "always" not in cell
        assert "not read" in cell
