"""manage_hardware_disposal: HAM Pro disposal, as the Workspace drives it.

Measured live, which these mocks cannot show: Verify/Depart/Dispose are
declarative actions posted to /api/now/ui/declarative_action/<assignment> (their
server script also moves the ASSET), and a task close the completion rule
refuses answers 200 with the state put back. The fake instance below reproduces
both so the guards around them stay pinned.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from servicenow_mcp.services import hardware_disposal as svc
from servicenow_mcp.tools.hardware_disposal_tools import (
    ManageHardwareDisposalParams,
    manage_hardware_disposal,
)
from servicenow_mcp.utils.config import AuthType

ORDER = "aaaa1111bbbb2222cccc3333dddd0201"
ROOM = "aaaa1111bbbb2222cccc3333dddd0202"
LOC = "aaaa1111bbbb2222cccc3333dddd0203"
USER = "aaaa1111bbbb2222cccc3333dddd0204"
ASSET = "aaaa1111bbbb2222cccc3333dddd0205"
ROW = "aaaa1111bbbb2222cccc3333dddd0206"
TASK = "aaaa1111bbbb2222cccc3333dddd0207"
ACTION = "aaaa1111bbbb2222cccc3333dddd0208"
VENDOR = "aaaa1111bbbb2222cccc3333dddd0209"
NEXT_TASK = "aaaa1111bbbb2222cccc3333dddd0210"


class Instance:
    """A scripted disposal order. Records writes; applies the platform's rules."""

    def __init__(
        self,
        *,
        stage="draft",
        task="verify",
        row_stage="draft",
        order=None,
        attachment=False,
        accept_close=True,
        actions=1,
        flow_opens_next=True,
    ):
        self.order = {
            "sys_id": ORDER,
            "number": "HWDIS0000001",
            "stage": stage,
            "stockroom": ROOM,
            "location": LOC,
            "assigned_to": USER,
            "scheduled_date": "",
            "vendor": "",
            "vendor_order_id": "",
            "pickup_contact": "",
            "certificate_of_disposal": "N",
        }
        self.order.update(order or {})
        self.tasks = [
            {"sys_id": TASK, "number": "HWDISTASK0000001", "task_name": task, "state": "1"}
        ]
        self.rows = [
            {
                "sys_id": ROW,
                "stage": row_stage,
                "hardware": ASSET,
                "hardware.asset_tag": "TAG-1",
                "hardware.serial_number": "SN-1",
            }
        ]
        self.attachment = attachment
        self.accept_close = accept_close
        self.actions = actions
        self.flow_opens_next = flow_opens_next
        self.writes = []

    # -- reads -------------------------------------------------------------
    def query(self, config, auth_manager, *, table, query, **kw):
        if table == svc.ORDER_TABLE:
            wanted = query.split("=", 1)[1]
            return ([dict(self.order)] if wanted in (ORDER, "HWDIS0000001") else []), None
        if table == svc.TASK_TABLE:
            if query.startswith("sys_id="):
                return [t for t in self.tasks if t["sys_id"] == query.split("=", 1)[1]], None
            return [dict(t) for t in self.tasks], None
        if table == svc.ASSET_ROW_TABLE:
            return [dict(r) for r in self.rows], None
        if table == svc.ACTION_TABLE:
            return [{"sys_id": ACTION}] * self.actions, None
        if table == "sys_attachment":
            return ([{"sys_id": "x"}] if self.attachment else []), None
        if table == "sys_user":
            return [{"sys_id": USER}], None
        if table in ("alm_stockroom", "cmn_location", "core_company"):
            return [{"sys_id": "x", "location": LOC}], None
        return [], None

    # -- writes ------------------------------------------------------------
    def request(self, method, url, **kw):
        path = url.split("test.service-now.com", 1)[1]
        self.writes.append((method, path, kw.get("json"), kw.get("params")))
        result: dict = {}
        if path.startswith("/api/now/ui/declarative_action/"):
            step = {"verify": "verified", "depart": "in_transit", "dispose": "completed"}
            for row in self.rows:
                if row["sys_id"] in kw["json"]["sysIds"].split(","):
                    row["stage"] = step[self._step]
        elif method == "PATCH" and svc.TASK_TABLE in path:
            if self.accept_close:
                self.tasks[0]["state"] = "3"
                if self.flow_opens_next:
                    self.tasks.append(
                        {
                            "sys_id": NEXT_TASK,
                            "number": "HWDISTASK0000002",
                            "task_name": "schedule",
                            "state": "1",
                        }
                    )
        elif method == "PATCH" and svc.ORDER_TABLE in path:
            self.order.update(kw["json"])
            result = dict(kw["json"])
        elif method == "POST" and svc.ORDER_TABLE in path:
            result = {"sys_id": ORDER}
        elif method == "POST" and svc.ASSET_ROW_TABLE in path:
            result = {"sys_id": ROW}
        elif "attachment" in path:
            result = {"sys_id": "att"}
        response = MagicMock()
        response.json.return_value = {"result": result}
        return response

    def __enter__(self):
        self.auth = MagicMock()
        self.auth.get_headers.return_value = {}
        self.auth.make_request.side_effect = self.request
        asset_row = {"sys_id": ASSET, "asset_tag": "TAG-1"}
        self._patches = [
            patch.object(svc, "sn_query_page", side_effect=self.query),
            patch.object(svc, "invalidate_query_cache"),
            patch.object(svc, "find_assets", return_value=[asset_row]),
            patch.object(svc, "_authenticated_user", return_value="alice"),
            patch.object(svc.time, "sleep"),
        ]
        for p in self._patches:
            p.start()
        return self

    def __exit__(self, *exc):
        for p in self._patches:
            p.stop()

    def run(self, auth_type=AuthType.BROWSER, **kw):
        self._step = kw.get("action")
        config = MagicMock(instance_url="https://test.service-now.com", timeout=10)
        config.auth.type = auth_type
        args = {"order": "HWDIS0000001"}
        args.update(kw)
        return manage_hardware_disposal(config, self.auth, ManageHardwareDisposalParams(**args))

    def paths(self, method):
        return [p for m, p, _, _ in self.writes if m == method]


class TestGet:
    def test_names_the_open_task_and_what_closing_it_needs(self):
        with Instance() as sn:
            out = sn.run(action="get")
        assert out["open_task"]["task"] == "verify"
        assert out["to_close"]["missing"] == ["at least one verified asset (action=verify)"]
        assert out["asset_stages"] == {"draft": 1}
        assert sn.writes == []

    def test_finished_order_says_so(self):
        with Instance(stage="completed") as sn:
            sn.tasks[0]["state"] = "3"
            out = sn.run(action="get")
        assert out["open_task"] is None and "finished" in out["note"]

    def test_missing_open_task_on_a_live_order_is_not_yet(self):
        with Instance(stage="scheduled") as sn:
            sn.tasks[0]["state"] = "3"
            out = sn.run(action="get")
        assert "Read again" in out["note"]


class TestCreate:
    def test_creates_order_then_rows(self):
        with Instance() as sn:
            out = sn.run(action="create", order=None, stockroom=ROOM, asset_ids=["TAG-1"])
        posts = [(p, j) for m, p, j, _ in sn.writes if m == "POST"]
        assert posts[0] == (
            f"/api/now/table/{svc.ORDER_TABLE}",
            {"stockroom": ROOM, "location": LOC, "assigned_to": USER},
        )
        assert posts[1] == (
            f"/api/now/table/{svc.ASSET_ROW_TABLE}",
            {"hardware_disposal": ORDER, "hardware": ASSET},
        )
        assert out["success"] is True

    def test_dry_run_writes_nothing(self):
        with Instance() as sn:
            out = sn.run(
                action="create", order=None, stockroom=ROOM, asset_ids=["TAG-1"], dry_run=True
            )
        assert out["dry_run"] is True and sn.writes == []

    def test_requires_assets(self):
        with pytest.raises(ValueError):
            ManageHardwareDisposalParams(action="create", stockroom=ROOM)


class TestSteps:
    def test_verify_posts_the_workspace_action(self):
        with Instance() as sn:
            out = sn.run(action="verify")
        method, path, body, params = sn.writes[0]
        assert (method, path) == ("POST", f"/api/now/ui/declarative_action/{ACTION}")
        assert params == {"sysparm_table": svc.ASSET_ROW_TABLE}
        assert body == {
            "sysIds": ROW,
            "query": f"hardware_disposal={ORDER}",
            "selectionQuery": f"sys_idIN{ROW}",
            "parentTable": svc.TASK_TABLE,
            "parentRecordSysId": TASK,
        }
        assert out["success"] is True and out["moved"][0]["stage"] == "verified"

    def test_wrong_open_task_is_refused(self):
        with Instance(task="verify") as sn:
            out = sn.run(action="depart")
        assert out["error"] == "WRONG_TASK" and sn.writes == []

    def test_nothing_in_the_right_stage(self):
        with Instance(row_stage="verified") as sn:
            out = sn.run(action="verify")
        assert out["error"] == "NOTHING_TO_DO" and sn.writes == []

    def test_basic_auth_cannot_run_a_step(self):
        with Instance() as sn:
            out = sn.run(action="verify", auth_type=AuthType.BASIC)
        assert out["error"] == "BROWSER_AUTH_REQUIRED"
        sn.auth.make_request.assert_not_called()

    def test_unresolvable_action_refuses(self):
        with Instance(actions=0) as sn:
            out = sn.run(action="verify")
        assert out["error"] == "ACTION_UNRESOLVED"
        assert sn.writes == []

    def test_row_that_did_not_move_is_not_success(self):
        with Instance() as sn:
            sn.request_orig = sn.request

            def no_move(method, url, **kw):
                if "declarative_action" in url:
                    sn.writes.append((method, url, kw.get("json"), kw.get("params")))
                    response = MagicMock()
                    response.json.return_value = {"result": {}}
                    return response
                return sn.request_orig(method, url, **kw)

            sn.auth.make_request.side_effect = no_move
            out = sn.run(action="verify")
        assert out["success"] is False and out["not_moved"][0]["stage"] == "draft"


class TestCompleteTask:
    def test_refuses_with_what_is_missing(self):
        with Instance(task="schedule", row_stage="verified") as sn:
            out = sn.run(action="complete_task")
        assert out["error"] == "TASK_NOT_READY"
        assert out["to_close"]["missing"] == ["order field scheduled_date", "order field vendor"]
        assert sn.writes == []

    def test_closes_and_reports_the_next_task(self):
        with Instance(row_stage="verified") as sn:
            out = sn.run(action="complete_task")
        assert sn.paths("PATCH") == [f"/api/now/table/{svc.TASK_TABLE}/{TASK}"]
        assert out["closed"] == "HWDISTASK0000001"
        assert out["open_task"]["task"] == "schedule"

    def test_platform_putting_the_state_back_is_not_closed(self):
        with Instance(row_stage="verified", accept_close=False) as sn:
            out = sn.run(action="complete_task")
        assert out["error"] == "TASK_NOT_CLOSED"

    def test_next_task_not_yet_visible_is_hedged(self):
        with Instance(row_stage="verified", flow_opens_next=False) as sn:
            with patch.object(svc.time, "monotonic", side_effect=[0.0, 0.0, 99.0, 99.0]):
                out = sn.run(action="complete_task")
        assert "not visible" in out["note"]

    def test_depart_needs_every_verified_asset_gone(self):
        order = {
            "scheduled_date": "d",
            "vendor": VENDOR,
            "vendor_order_id": "v",
            "pickup_contact": "p",
        }
        with Instance(task="depart", row_stage="verified", order=order) as sn:
            out = sn.run(action="complete_task")
        assert (
            "1 verified asset(s) still to depart or cancel (action=depart)"
            in out["to_close"]["missing"]
        )

    def test_documentation_needs_certificate_and_disposed_assets(self):
        with Instance(task="documentation", row_stage="pending_certificate") as sn:
            out = sn.run(action="complete_task")
        missing = out["to_close"]["missing"]
        assert any("attach" in m for m in missing)
        assert any("certificate_of_disposal" in m for m in missing)
        assert any("still to dispose" in m for m in missing)

    def test_capped_asset_rows_are_undetermined(self):
        with Instance(row_stage="verified") as sn:
            sn.rows = sn.rows * (svc.MAX_ASSET_ROWS + 1)
            out = sn.run(action="complete_task")
        assert out["error"] == "REQUIREMENTS_UNDETERMINED" and sn.writes == []


class TestUpdateAndCertificate:
    def test_update_checks_references_and_reports(self):
        with Instance() as sn:
            out = sn.run(action="update", scheduled_date="2026-01-01 10:00:00", vendor=VENDOR)
        assert out["success"] is True and out["updated"] == ["scheduled_date", "vendor"]

    def test_certificate_only_on_documentation(self, tmp_path):
        cert = tmp_path / "cert.txt"
        cert.write_text("ok")
        with Instance(task="verify") as sn:
            out = sn.run(action="attach_certificate", file_path=str(cert))
        assert out["error"] == "WRONG_TASK" and sn.writes == []

    def test_certificate_uploads_and_sets_yes(self, tmp_path):
        cert = tmp_path / "cert.txt"
        cert.write_text("ok")
        with Instance(task="documentation") as sn:
            out = sn.run(action="attach_certificate", file_path=str(cert))
        methods = [(m, p.split("?")[0]) for m, p, _, _ in sn.writes]
        assert methods[0] == ("POST", "/api/now/attachment/file")
        assert sn.order["certificate_of_disposal"] == "Y"
        assert out["attachment_id"] == "att"

    def test_missing_file(self):
        with Instance(task="documentation") as sn:
            out = sn.run(action="attach_certificate", file_path="/nonexistent/cert.pdf")
        assert out["error"] == "FILE_NOT_FOUND"


def test_add_assets_refused_after_transit():
    with Instance(stage="pending_certificate") as sn:
        out = sn.run(action="add_assets", asset_ids=["TAG-1"])
    assert out["error"] == "ORDER_CLOSED_TO_ASSETS" and sn.writes == []


def test_get_is_a_read_for_the_write_gate():
    from servicenow_mcp.policies.write_guards import MANAGE_READ_ACTIONS

    assert MANAGE_READ_ACTIONS["manage_hardware_disposal"] == frozenset({"get"})
    assert json.dumps(sorted(svc.STEPS)) == '["depart", "dispose", "verify"]'
