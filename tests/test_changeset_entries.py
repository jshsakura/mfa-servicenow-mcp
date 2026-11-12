"""manage_changeset move_file / remove_file — taking a wrong entry out of an update set.

The fake below is a tiny in-memory instance: reads answer from the same store
that PATCH / DELETE change, so the read-back verification is exercised for real
rather than echoing a fixture.
"""

from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock, patch

import pytest
from pydantic import ValidationError

from servicenow_mcp.services import changeset as svc
from servicenow_mcp.tools.changeset_tools import ManageChangesetParams, manage_changeset
from servicenow_mcp.utils.config import AuthConfig, AuthType, BasicAuthConfig, ServerConfig

SRC = "aaaa1111bbbb2222cccc3333dddd4444"
TGT = "aaaa1111bbbb2222cccc3333dddd5555"
CLOSED = "aaaa1111bbbb2222cccc3333dddd6666"
OTHER_APP_SET = "aaaa1111bbbb2222cccc3333dddd7777"
E1 = "eeee1111bbbb2222cccc3333dddd0001"
E2 = "eeee1111bbbb2222cccc3333dddd0002"
E3 = "eeee1111bbbb2222cccc3333dddd0003"
ELSEWHERE = "eeee1111bbbb2222cccc3333dddd0004"
MISSING = "eeee1111bbbb2222cccc3333dddd0009"
APP = "ffff1111bbbb2222cccc3333dddd0000"
APP2 = "ffff1111bbbb2222cccc3333dddd9999"
ME = "alice"


def _config():
    return ServerConfig(
        instance_url="https://test.service-now.com",
        auth=AuthConfig(type=AuthType.BASIC, basic=BasicAuthConfig(username=ME, password="p")),
    )


class FakeInstance:
    def __init__(self):
        self.sets: Dict[str, Dict[str, Any]] = {
            SRC: {
                "sys_id": SRC,
                "name": "Sprint 12 fixes",
                "state": "in progress",
                "application": APP,
            },
            TGT: {"sys_id": TGT, "name": "Parking", "state": "in progress", "application": APP},
            CLOSED: {"sys_id": CLOSED, "name": "Done", "state": "complete", "application": APP},
            OTHER_APP_SET: {
                "sys_id": OTHER_APP_SET,
                "name": "Other app",
                "state": "in progress",
                "application": APP2,
            },
        }
        self.entries: Dict[str, Dict[str, Any]] = {
            E1: self._entry(E1, "sys_script_include_aaaa0001", SRC),
            E2: self._entry(E2, "sys_script_aaaa0002", SRC),
            E3: self._entry(E3, "sys_script_aaaa0003", SRC),
            ELSEWHERE: self._entry(ELSEWHERE, "sys_script_aaaa0004", TGT),
        }
        self.writes: List[tuple] = []
        self.fail_write_on: Optional[str] = None
        self.refusal_body: Optional[dict] = None
        self.ignore_writes = False
        self.fail_reads_after_write = False

    @staticmethod
    def _entry(sys_id, name, update_set, by=ME):
        return {
            "sys_id": sys_id,
            "name": name,
            "target_name": name.upper(),
            "type": "Script Include",
            "action": "INSERT_OR_UPDATE",
            "update_set": update_set,
            "application": APP,
            "sys_created_by": by,
            "sys_updated_by": by,
        }

    def query_page(self, config, auth_manager, *, table, query, fields, limit, offset, **kw):
        assert kw.get("fail_silently") is False, "every read here must fail loudly"
        if self.fail_reads_after_write and self.writes:
            raise RuntimeError("HTTP 503")
        if table == "sys_update_set":
            sys_id = query.removeprefix("sys_id=")
            row = self.sets.get(sys_id)
            return ([dict(row)] if row else []), None
        assert table == "sys_update_xml"
        if query.startswith("sys_idIN"):
            ids = query.removeprefix("sys_idIN").split(",")
            return [dict(self.entries[i]) for i in ids if i in self.entries], None
        head, names = query.split("^nameIN")
        target = head.removeprefix("update_set=")
        wanted = set(names.split(","))
        rows = [
            dict(e)
            for e in self.entries.values()
            if e["update_set"] == target and e["name"] in wanted
        ]
        return rows, None

    def make_request(self, method, url, json=None, headers=None, **kw):
        sys_id = url.rsplit("/", 1)[-1]
        self.writes.append((method, sys_id, json))
        response = MagicMock()
        if sys_id == self.fail_write_on:
            err = RuntimeError("HTTP 403 Forbidden")
            if self.refusal_body is not None:
                err.response = MagicMock(status_code=403)
                err.response.json.return_value = self.refusal_body
            response.raise_for_status.side_effect = err
            return response
        if not self.ignore_writes:
            if method == "PATCH":
                self.entries[sys_id]["update_set"] = json["update_set"]
            elif method == "DELETE":
                self.entries.pop(sys_id)
        return response


@pytest.fixture
def inst():
    fake = FakeInstance()
    auth = MagicMock()
    auth.get_headers.return_value = {}
    auth.make_request.side_effect = fake.make_request
    fake.auth = auth
    with (
        patch.object(svc, "sn_query_page", side_effect=fake.query_page),
        patch("servicenow_mcp.tools.sn_api._authenticated_user", return_value=ME),
    ):
        yield fake


def _call(inst, **kwargs):
    return manage_changeset(_config(), inst.auth, ManageChangesetParams(**kwargs))


def _move(inst, ids, **extra):
    return _call(
        inst,
        action="move_file",
        changeset_id=SRC,
        entry_ids=ids,
        target_changeset_id=TGT,
        **extra,
    )


def _remove(inst, ids, **extra):
    return _call(inst, action="remove_file", changeset_id=SRC, entry_ids=ids, **extra)


# ---------------------------------------------------------------------------
# What the arguments may be
# ---------------------------------------------------------------------------


class TestArguments:
    def test_entry_ids_are_required(self):
        with pytest.raises(ValidationError, match="entry_ids is required"):
            ManageChangesetParams(action="remove_file", changeset_id=SRC)

    def test_names_and_queries_are_not_entry_ids(self):
        with pytest.raises(ValidationError, match="32-character sys_ids"):
            ManageChangesetParams(action="remove_file", changeset_id=SRC, entry_ids=["nameLIKEfoo"])

    def test_batch_is_capped(self):
        ids = [f"eeee1111bbbb2222cccc3333dd{n:06x}" for n in range(svc.MAX_ENTRY_BATCH + 1)]
        with pytest.raises(ValidationError, match="at most"):
            ManageChangesetParams(action="remove_file", changeset_id=SRC, entry_ids=ids)

    def test_move_needs_a_different_target(self):
        with pytest.raises(ValidationError, match="target_changeset_id is required"):
            ManageChangesetParams(action="move_file", changeset_id=SRC, entry_ids=[E1])
        with pytest.raises(ValidationError, match="same set"):
            ManageChangesetParams(
                action="move_file", changeset_id=SRC, entry_ids=[E1], target_changeset_id=SRC
            )

    def test_ids_are_deduplicated_and_lowercased(self):
        p = ManageChangesetParams(
            action="remove_file", changeset_id=SRC, entry_ids=[E1.upper(), E1, " "]
        )
        assert p.entry_ids == [E1]

    def test_both_actions_are_writes(self):
        from servicenow_mcp.policies.write_guards import _is_read_only

        for action in ("move_file", "remove_file"):
            assert not _is_read_only("manage_changeset", {"action": action})


# ---------------------------------------------------------------------------
# move_file
# ---------------------------------------------------------------------------


class TestMove:
    def test_dry_run_writes_nothing_and_lists_the_entries(self, inst):
        result = _move(inst, [E1, E2], dry_run=True)
        assert result["success"] is True and result["written"] is False
        assert inst.writes == []
        assert [e["sys_id"] for e in result["entries"]] == [E1, E2]
        assert result["approvals_required"] == {}
        assert "Parking" in result["message"]

    def test_move_is_written_and_verified(self, inst):
        result = _move(inst, [E1, E2])
        assert result["success"] is True and result["verified"] is True
        assert inst.entries[E1]["update_set"] == TGT
        assert inst.entries[E2]["update_set"] == TGT
        assert [w[0] for w in inst.writes] == ["PATCH", "PATCH"]
        assert "record itself still holds the edit" in result["note"]

    def test_closed_source_is_left_alone(self, inst):
        inst.sets[SRC]["state"] = "complete"
        result = _move(inst, [E1])
        assert result["success"] is False and "not in progress" in result["message"]
        assert inst.writes == []

    def test_closed_target_is_refused(self, inst):
        result = _call(
            inst, action="move_file", changeset_id=SRC, entry_ids=[E1], target_changeset_id=CLOSED
        )
        assert result["success"] is False and "open set" in result["message"]
        assert inst.writes == []

    def test_target_in_another_application_is_refused(self, inst):
        result = _call(
            inst,
            action="move_file",
            changeset_id=SRC,
            entry_ids=[E1],
            target_changeset_id=OTHER_APP_SET,
        )
        assert result["success"] is False and "different applications" in result["message"]
        assert inst.writes == []

    def test_unreadable_application_is_not_a_match(self, inst):
        inst.sets[TGT]["application"] = ""
        result = _move(inst, [E1])
        assert result["success"] is False and "could not be read" in result["message"]
        assert inst.writes == []

    def test_one_entry_from_another_set_refuses_the_whole_batch(self, inst):
        result = _move(inst, [E1, ELSEWHERE])
        assert result["success"] is False and "whole batch" in result["message"]
        assert result["not_in_source"][0]["sys_id"] == ELSEWHERE
        assert inst.writes == []

    def test_missing_entry_refuses_the_whole_batch(self, inst):
        result = _move(inst, [E1, MISSING])
        assert result["success"] is False and result["missing"] == [MISSING]
        assert inst.writes == []

    def test_entry_of_another_application_is_refused(self, inst):
        inst.entries[E1]["application"] = APP2
        result = _move(inst, [E1])
        assert result["success"] is False and result["wrong_application"] == [E1]
        assert inst.writes == []

    def test_target_already_holding_the_record_is_refused(self, inst):
        inst.entries[ELSEWHERE]["name"] = inst.entries[E1]["name"]
        result = _move(inst, [E1])
        assert result["success"] is False and "two versions" in result["message"]
        assert result["already_in_target"][0]["sys_id"] == ELSEWHERE
        assert inst.writes == []


# ---------------------------------------------------------------------------
# remove_file
# ---------------------------------------------------------------------------


class TestRemove:
    def test_needs_the_set_name(self, inst):
        result = _remove(inst, [E1])
        assert (
            result["success"] is False and "confirm_remove='Sprint 12 fixes'" in result["message"]
        )
        assert inst.writes == []

    def test_bare_approve_is_not_the_set_name(self, inst):
        result = _remove(inst, [E1], confirm_remove="approve")
        assert result["success"] is False
        assert inst.writes == []

    def test_dry_run_names_the_approval(self, inst):
        result = _remove(inst, [E1], dry_run=True)
        assert result["success"] is True and result["written"] is False
        assert result["approvals_required"] == {"confirm_remove": "Sprint 12 fixes"}
        assert "Still needed" in result["message"]
        assert inst.writes == []

    def test_remove_is_written_and_verified(self, inst):
        result = _remove(inst, [E1, E2], confirm_remove="sprint 12 FIXES")
        assert result["success"] is True and result["verified"] is True
        assert E1 not in inst.entries and E2 not in inst.entries
        assert E3 in inst.entries
        assert "record itself still holds the edit" in result["note"]


# ---------------------------------------------------------------------------
# Someone else's work
# ---------------------------------------------------------------------------


class TestOtherAuthors:
    def test_other_authors_entry_needs_their_name(self, inst):
        inst.entries[E1]["sys_updated_by"] = "bob"
        result = _move(inst, [E1])
        assert result["success"] is False and "'bob'" in result["message"]
        assert result["approvals_required"] == {"confirm_other_author": "bob"}
        assert inst.writes == []

    def test_named_approval_lets_it_through(self, inst):
        inst.entries[E1]["sys_updated_by"] = "bob"
        result = _move(inst, [E1], confirm_other_author="Bob")
        assert result["success"] is True and result["verified"] is True

    def test_every_other_author_must_be_named(self, inst):
        inst.entries[E1]["sys_updated_by"] = "bob"
        inst.entries[E2]["sys_created_by"] = "other.dev"
        result = _move(inst, [E1, E2], confirm_other_author="bob")
        assert result["success"] is False
        assert result["approvals_required"]["confirm_other_author"] == "bob,other.dev"
        assert inst.writes == []

    def test_an_unreadable_author_is_not_you(self, inst):
        inst.entries[E1]["sys_created_by"] = ""
        result = _move(inst, [E1])
        assert result["success"] is False
        assert result["approvals_required"]["confirm_other_author"] == "unknown"
        assert inst.writes == []

    def test_unresolved_session_names_nobody_as_you(self, inst):
        with patch("servicenow_mcp.tools.sn_api._authenticated_user", return_value=None):
            result = _move(inst, [E1])
        assert result["success"] is False
        assert "could not be confirmed" in result["message"]
        assert result["approvals_required"]["confirm_other_author"] == ME
        assert inst.writes == []


# ---------------------------------------------------------------------------
# Failures say what they proved
# ---------------------------------------------------------------------------


class TestFailures:
    def test_unreadable_source_writes_nothing(self, inst):
        with patch.object(svc, "sn_query_page", side_effect=RuntimeError("HTTP 500")):
            result = _move(inst, [E1])
        assert result["success"] is False and result["written"] is False
        assert "nothing was changed" in result["message"]
        assert inst.writes == []

    def test_a_failed_write_stops_the_batch(self, inst):
        inst.fail_write_on = E2
        result = _remove(inst, [E1, E2, E3], confirm_remove="Sprint 12 fixes")
        assert result["success"] is False and result["written"] is True
        assert result["done"] == [E1]
        assert result["not_done"] == [E2, E3]
        assert E3 in inst.entries
        assert "The rest were not touched" in result["message"]

    def test_a_refusal_carries_the_servers_reason(self, inst):
        inst.fail_write_on = E1
        inst.refusal_body = {"error": {"message": "Operation Failed", "detail": "ACL Exception"}}
        result = _remove(inst, [E1, E2], confirm_remove="Sprint 12 fixes")
        assert result["failure"]["http_status"] == 403
        assert result["failure"]["server_message"] == "Operation Failed — ACL Exception"
        assert result["failure"]["reason"] == "WRITE_REFUSED"
        assert "server said: Operation Failed — ACL Exception" in result["message"]

    def test_unreadable_read_back_is_not_verified(self, inst):
        inst.fail_reads_after_write = True
        result = _move(inst, [E1])
        assert result["written"] is True
        assert result["verified"] is False and result["success"] is False
        assert "not verified" in result["message"]

    def test_accepted_but_unchanged_is_reported(self, inst):
        inst.ignore_writes = True
        result = _move(inst, [E1])
        assert result["verified"] is False and result["success"] is False
        assert result["verification"]["mismatched"] == [E1]
