"""manage_procurement receive: the Receive page's own server path, checked first.

Measured, which these mocks cannot show: over the Table API the receiving line's
purchase_line / quantity are dropped by field ACL (200, empty line), so the tool
calls POReceiveManager through /procurement_processor.do as the page does. A form
POST to it answers an empty body; GET is the call that works. What the server
says about the line (receivable, mandatory identifiers, model type) comes from
its own getPOItems and is not re-derived.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from servicenow_mcp.services import procurement as svc
from servicenow_mcp.tools.procurement_tools import ManageProcurementParams, manage_procurement
from servicenow_mcp.utils.config import AuthType

LINE = "aaaa1111bbbb2222cccc3333dddd0101"
PO = "aaaa1111bbbb2222cccc3333dddd0102"
ROOM = "aaaa1111bbbb2222cccc3333dddd0103"
OTHER_ROOM = "aaaa1111bbbb2222cccc3333dddd0104"
OLD_RL = "aaaa1111bbbb2222cccc3333dddd0105"
NEW_RL = "aaaa1111bbbb2222cccc3333dddd0106"
ASSET_1 = "aaaa1111bbbb2222cccc3333dddd0107"
USER = "aaaa1111bbbb2222cccc3333dddd0108"


def _item(**over):
    item = {
        "sys_id": LINE,
        "number": "POL0000001",
        "status": "ordered",
        "remaining_quantity": "4",
        "received_quantity": "0",
        "sys_mod_count": "1",
        "cost": "1234567.5",
        "item_model_type": "asset",
        "is_serial_number_mandatory": True,
        "is_asset_tag_mandatory": False,
        "is_mac_address_mandatory": False,
        "pre_created_assets": [],
        "model": {"sys_id": "m", "asset_tracking_strategy": "leave_to_category"},
        "purchase_order": {"sys_id": PO, "number": "PO0000001", "ship_to": {"sys_id": ROOM}},
        "requested_for": "",
    }
    item.update(over)
    return item


class Instance:
    """A scripted instance; records the receive call it is sent."""

    def __init__(
        self,
        *,
        item=None,
        offered=True,
        page_answer=None,
        receive_answer=None,
        creates=True,
        assets=None,
        in_use=(),
        currency=({"reference_amount": "1000.5", "reference_currency.code": "USD"},),
        rooms=(ROOM, OTHER_ROOM),
        line_after=None,
    ):
        self.item = _item(**(item or {}))
        self.offered = offered
        self.page_answer = page_answer
        self.receive_answer = (
            receive_answer
            if receive_answer is not None
            else {"status": "success", "failedAssets": {}}
        )
        self.creates = creates
        self.assets = assets if assets is not None else [{"sys_id": ASSET_1}]
        self.in_use = set(in_use)
        self.currency = list(currency)
        self.rooms = set(rooms)
        self.line_after = line_after or {"remaining_quantity": "3", "received_quantity": "1"}
        self.received = None

    def query(self, config, auth_manager, *, table, query, **kw):
        if table == "proc_po_item":
            if self.received is not None:
                return [self.line_after], None
            wanted = query.split("=", 1)[1]
            if wanted in (LINE, "POL0000001"):
                return [
                    {
                        "sys_id": LINE,
                        "number": "POL0000001",
                        "status": "ordered",
                        "remaining_quantity": "4",
                        "purchase_order": PO,
                    }
                ], None
            return [], None
        if table == "proc_rec_slip_item":
            rows = [{"sys_id": OLD_RL}]
            if self.received is not None and self.creates:
                rows.append({"sys_id": NEW_RL})
            return rows, None
        if table == "fx_currency_instance":
            return self.currency, None
        if table == "alm_stockroom":
            wanted = query.split("=", 1)[1]
            return ([{"sys_id": wanted}] if wanted in self.rooms else []), None
        if table == "alm_asset":
            if query.startswith("receiving_lineIN"):
                return [dict(a) for a in self.assets], None
            column, values = query.split("IN", 1)
            return [{column: v} for v in values.split(",") if v in self.in_use], None
        return [], None

    def request(self, method, url, params=None, **kw):
        assert url.endswith("/procurement_processor.do") and method == "GET"
        assert params["sysparm_processor"] == "POReceiveManager"
        response = MagicMock()
        if params["sysparm_name"] == "getPOItems":
            assert params["sysparm_po_sysid"] == PO
            answer = (
                self.page_answer
                if self.page_answer is not None
                else ([self.item] if self.offered else [])
            )
        else:
            self.received = params
            answer = self.receive_answer
        response.text = answer if isinstance(answer, str) else json.dumps(answer)
        return response

    def __enter__(self):
        self.auth = MagicMock()
        self.auth.make_request.side_effect = self.request
        self._patches = [
            patch.object(svc, "sn_query_page", side_effect=self.query),
            patch.object(svc, "invalidate_query_cache"),
        ]
        for p in self._patches:
            p.start()
        return self

    def __exit__(self, *exc):
        for p in self._patches:
            p.stop()

    def run(self, auth_type=AuthType.BROWSER, **kw):
        config = MagicMock(instance_url="https://test.service-now.com", timeout=10)
        config.auth.type = auth_type
        args = {"action": "receive", "po_line": "POL0000001", "quantity": 1}
        args.update(kw)
        return manage_procurement(config, self.auth, ManageProcurementParams(**args))

    def sent_line(self):
        assert self.received is not None
        assert self.received["sysparm_po_sysid"] == PO
        assert self.received["sysparm_batching"] == "none"
        return json.loads(self.received["sysparm_receivedata"])[0]


class TestHappyPath:
    def test_receives_through_the_page_and_reports_what_the_server_holds(self):
        with Instance() as sn:
            out = sn.run(serial_numbers=["SN-1"], asset_tags=["TAG-1"])
        line = sn.sent_line()
        assert line["receive"] is True and line["receiving_quantity"] == "1"
        assert line["cost_with_currency"] == "USD;1000.5"
        assert line["ship_to"] == {"value": ROOM}
        assert line["assetTags"] == [{"asset_tag": "TAG-1", "serial_number": "SN-1"}]
        assert "remaining_quantity" not in line and "sys_mod_count" not in line
        assert out["success"] is True
        assert out["receiving_lines"] == [NEW_RL]
        assert out["assets"] == [{"sys_id": ASSET_1}]
        assert "warnings" not in out

    def test_session_currency_cost_is_never_sent(self):
        with Instance() as sn:
            sn.run(serial_numbers=["SN-1"])
        assert "1234567.5" not in sn.sent_line()["cost_with_currency"]

    def test_dry_run_never_calls_receive(self):
        with Instance() as sn:
            out = sn.run(serial_numbers=["SN-1"], dry_run=True)
        assert out["dry_run"] is True and sn.received is None
        assert out["plan"]["required_by_page"] == ["serial_number"]
        assert out["plan"]["cost"] == "USD;1000.5"

    def test_reserve_and_other_stockroom(self):
        with Instance() as sn:
            sn.run(serial_numbers=["SN-1"], reserve=True, stockroom=OTHER_ROOM, requested_for=USER)
        line = sn.sent_line()
        assert line["reserved"] is True
        assert line["ship_to"] == {"value": OTHER_ROOM}
        assert line["reserved_for"] == {"value": USER}

    def test_no_identifiers_sends_no_asset_details(self):
        with Instance(item={"is_serial_number_mandatory": False}) as sn:
            sn.run()
        assert "assetTags" not in sn.sent_line()

    def test_do_not_track_expects_no_assets(self):
        item = {
            "is_serial_number_mandatory": False,
            "model": {"asset_tracking_strategy": "do_not_track"},
        }
        with Instance(item=item, assets=[]) as sn:
            out = sn.run()
        assert out["success"] is True


class TestRefusals:
    @pytest.mark.parametrize(
        "kw, inst, error",
        [
            ({"quantity": 5, "serial_numbers": ["A"]}, {}, "OVER_RECEIVE"),
            ({"po_line": "POL9999999"}, {}, "PO_LINE_NOT_FOUND"),
            ({"serial_numbers": ["A"]}, {"offered": False}, "NOT_RECEIVABLE"),
            (
                {"serial_numbers": ["A"]},
                {"page_answer": "<html>login</html>"},
                "RECEIVE_PAGE_UNREADABLE",
            ),
            ({"serial_numbers": ["A"]}, {"page_answer": {"error": "x"}}, "RECEIVE_PAGE_UNREADABLE"),
            ({}, {}, "IDENTIFIER_REQUIRED"),
            ({"serial_numbers": ["A"]}, {"in_use": {"A"}}, "IDENTIFIER_IN_USE"),
            ({"serial_numbers": ["A"]}, {"currency": ()}, "COST_UNVERIFIED"),
            (
                {"serial_numbers": ["A"], "stockroom": "aaaa1111bbbb2222cccc3333dddd0999"},
                {},
                "STOCKROOM_NOT_FOUND",
            ),
            ({"serial_numbers": ["A", "B"]}, {}, "TOO_MANY_IDENTIFIERS"),
            ({"quantity": 2, "serial_numbers": ["A", "A"]}, {}, "DUPLICATE_IDENTIFIER"),
            ({"quantity": 0}, {}, "BAD_QUANTITY"),
        ],
    )
    def test_refused_before_the_receive_call(self, kw, inst, error):
        with Instance(**inst) as sn:
            out = sn.run(**kw)
        assert out["error"] == error
        assert sn.received is None

    @pytest.mark.parametrize("model_type", ["software", "consumable", "bundle", ""])
    def test_only_asset_lines(self, model_type):
        with Instance(item={"item_model_type": model_type}) as sn:
            out = sn.run(serial_numbers=["A"])
        assert out["error"] == "UNSUPPORTED_LINE_TYPE" and sn.received is None

    def test_asset_tag_required_by_the_page(self):
        with Instance(item={"is_asset_tag_mandatory": True}) as sn:
            out = sn.run(serial_numbers=["A"])
        assert out["error"] == "IDENTIFIER_REQUIRED" and "asset_tag" in out["message"]

    def test_mac_required(self):
        with Instance(item={"is_mac_address_mandatory": True}) as sn:
            out = sn.run(serial_numbers=["A"])
        assert out["error"] == "MAC_REQUIRED" and sn.received is None

    def test_precreated_assets_with_identifiers(self):
        with Instance(item={"pre_created_assets": [{"sys_id": ASSET_1}]}) as sn:
            out = sn.run(serial_numbers=["A"])
        assert out["error"] == "PRECREATED_ASSETS" and sn.received is None

    def test_do_not_track_has_nothing_to_tag(self):
        item = {"model": {"asset_tracking_strategy": "do_not_track"}}
        with Instance(item=item) as sn:
            out = sn.run(serial_numbers=["A"])
        assert out["error"] == "NOT_TRACKED"

    def test_basic_auth_is_refused_without_a_call(self):
        with Instance() as sn:
            out = sn.run(auth_type=AuthType.BASIC, serial_numbers=["A"])
        assert out["error"] == "BROWSER_AUTH_REQUIRED"
        sn.auth.make_request.assert_not_called()


class TestProof:
    def test_unreadable_receive_answer_is_unconfirmed_not_failed(self):
        with Instance(receive_answer="") as sn:
            out = sn.run(serial_numbers=["A"])
        assert out["error"] == "RECEIVE_UNCONFIRMED"
        assert LINE in out["message"]

    def test_nothing_created_is_not_success(self):
        with Instance(creates=False, line_after={"remaining_quantity": "4"}) as sn:
            out = sn.run(serial_numbers=["A"])
        assert out["success"] is False
        assert any("nothing was received" in w for w in out["warnings"])

    def test_failed_units_are_not_success(self):
        answer = {"status": "success", "failedAssets": {LINE: {"items": [{"serial_number": "A"}]}}}
        with Instance(receive_answer=answer) as sn:
            out = sn.run(serial_numbers=["A"])
        assert out["success"] is False and out["failed_assets"]

    def test_remaining_that_did_not_move_is_a_warning(self):
        with Instance(line_after={"remaining_quantity": "4"}) as sn:
            out = sn.run(serial_numbers=["A"])
        assert out["success"] is False
        assert any("expected 3" in w for w in out["warnings"])

    def test_asset_count_mismatch_is_a_warning(self):
        with Instance(assets=[]) as sn:
            out = sn.run(serial_numbers=["A"])
        assert any("0 asset(s)" in w for w in out["warnings"])
