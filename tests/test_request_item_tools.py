"""manage_request_item: validated ordering, re-read proof, applied:false, wiring."""

import unittest
from unittest.mock import MagicMock, patch

import pytest
from pydantic import ValidationError

from servicenow_mcp.auth.auth_manager import AuthManager
from servicenow_mcp.tools.request_item_tools import ManageRequestItemParams, manage_request_item
from servicenow_mcp.utils.config import ServerConfig

MOD = "servicenow_mcp.tools.request_item_tools"
ITEM = "aaaa1111bbbb2222cccc3333dddd4444"
REQ = "bbbb2222cccc3333dddd4444eeee5555"
RITM = "cccc3333dddd4444eeee5555ffff6666"
SET = "dddd4444eeee5555ffff6666aaaa1111"


def _var(name, mandatory="false", default=""):
    return {
        "name": name,
        "mandatory": mandatory,
        "active": "true",
        "type": "6",
        "default_value": default,
    }


class Base(unittest.TestCase):
    def setUp(self):
        self.config = MagicMock(spec=ServerConfig)
        self.config.api_url = "https://test.service-now.com/api/now"
        self.config.instance_url = "https://test.service-now.com"
        self.config.timeout = 30
        self.auth = MagicMock(spec=AuthManager)
        self.auth.get_headers.return_value = {}
        self.tables = {}
        self.calls = []
        p = patch(f"{MOD}.sn_query_page", side_effect=self._query)
        p.start()
        self.addCleanup(p.stop)
        p = patch("servicenow_mcp.tools._preview.sn_query_page", side_effect=self._query)
        p.start()
        self.addCleanup(p.stop)
        p = patch(f"{MOD}.invalidate_query_cache")
        p.start()
        self.addCleanup(p.stop)

    def _query(self, config, auth, **kw):
        self.calls.append(kw)
        rows = self.tables.get(kw["table"], [])
        if callable(rows):
            rows = rows(kw)
        return list(rows), len(rows)

    def _post(self, body, status_result=None):
        resp = MagicMock()
        resp.json.return_value = {"result": body}
        self.auth.make_request.return_value = resp

    def run_tool(self, **kw):
        return manage_request_item(self.config, self.auth, ManageRequestItemParams(**kw))

    def writes(self):
        return self.auth.make_request.call_args_list


class TestOrder(Base):
    def setUp(self):
        super().setUp()
        self.tables["item_option_new"] = lambda kw: (
            [_var("shared_note")]
            if "variable_setIN" in kw["query"]
            else [_var("laptop_model", "true"), _var("reason", "true", default="n/a")]
        )
        self.tables["io_set_item"] = [{"variable_set": SET}]
        self.tables["item_option_new_set"] = [
            {"sys_id": SET, "internal_name": "shared", "type": "one_to_one"}
        ]

    def test_unknown_variable_refused_no_post(self):
        r = self.run_tool(
            action="order", item_id=ITEM, variables={"laptop_model": "x", "typo_var": "y"}
        )
        self.assertFalse(r["success"])
        self.assertEqual(r["error"], "UNKNOWN_VARIABLES")
        self.assertEqual(r["unknown"], ["typo_var"])
        self.auth.make_request.assert_not_called()

    def test_missing_mandatory_refused_but_default_ok(self):
        r = self.run_tool(action="order", item_id=ITEM, variables={"shared_note": "n"})
        self.assertEqual(r["error"], "MISSING_MANDATORY")
        self.assertEqual(r["missing"], ["laptop_model"])  # 'reason' has a default
        self.auth.make_request.assert_not_called()

    def test_set_variables_are_known(self):
        r = self.run_tool(
            action="order",
            item_id=ITEM,
            dry_run=True,
            variables={"laptop_model": "x", "shared_note": "n"},
        )
        self.assertTrue(r["dry_run"])
        self.assertEqual(r["payload"]["sysparm_quantity"], "1")
        self.auth.make_request.assert_not_called()

    def test_happy_path_reread_proof(self):
        self._post(
            {
                "request_number": "REQ0000001",
                "request_id": REQ,
                "number": "REQ0000001",
                "sys_id": REQ,
                "table": "sc_request",
            }
        )
        self.tables["sc_request"] = [
            {"sys_id": REQ, "number": "REQ0000001", "stage": "Request Approved", "state": "Open"}
        ]
        self.tables["sc_req_item"] = [
            {
                "sys_id": RITM,
                "number": "RITM0000001",
                "state": "Open",
                "stage": "Fulfillment",
                "cat_item": ITEM,
            }
        ]
        r = self.run_tool(
            action="order",
            item_id=ITEM,
            quantity=2,
            requested_for=SET,
            variables={"laptop_model": "x"},
        )
        self.assertTrue(r["confirmed"])
        self.assertEqual(r["items"][0]["number"], "RITM0000001")
        self.assertTrue(r["items"][0]["cat_item_ok"])
        method, url = self.writes()[0].args
        self.assertEqual(method, "POST")
        self.assertTrue(url.endswith(f"/items/{ITEM}/order_now"))
        body = self.writes()[0].kwargs["json"]
        self.assertEqual(body["sysparm_quantity"], "2")
        self.assertEqual(body["sysparm_requested_for"], SET)

    def test_unconfirmed_without_request_id(self):
        self._post({"number": "REQ0000002", "sys_id": REQ})
        r = self.run_tool(action="order", item_id=ITEM, variables={"laptop_model": "x"})
        self.assertTrue(r["success"])
        self.assertFalse(r["confirmed"])
        self.assertIn("unconfirmed", r["message"])


class TestFulfilment(Base):
    def _ritm(self, state="1"):
        return {
            "sys_id": RITM,
            "number": "RITM0000001",
            "state": state,
            "stage": "Fulfillment",
            "request": REQ,
            "short_description": "x",
        }

    def test_set_state_by_name_applied(self):
        seq = [[self._ritm("1")], [self._ritm("2")]]
        self.tables["sc_req_item"] = lambda kw: seq.pop(0) if len(seq) > 1 else seq[0]
        self._post({})
        r = self.run_tool(action="set_state", record_id="RITM0000001", state="work in progress")
        self.assertTrue(r["applied"])
        self.assertEqual(self.writes()[0].kwargs["json"], {"state": "2"})
        self.assertEqual(r["stage"], "Fulfillment")

    def test_applied_false_when_reread_differs(self):
        self.tables["sc_req_item"] = [self._ritm("1")]
        self._post({})
        r = self.run_tool(action="set_state", record_id="RITM0000001", state="Closed Complete")
        self.assertFalse(r["applied"])
        self.assertFalse(r["success"])
        self.assertEqual(r["state"]["value"], "1")

    def test_unknown_state_refused(self):
        r = self.run_tool(action="set_state", record_id="RITM0000001", state="Bogus")
        self.assertEqual(r["error"], "UNKNOWN_CHOICE")
        self.auth.make_request.assert_not_called()

    def test_add_task_wires_request_and_item(self):
        self.tables["sc_req_item"] = [self._ritm()]
        self.tables["sc_task"] = [
            {
                "sys_id": SET,
                "number": "SCTASK0000001",
                "state": "1",
                "request_item": RITM,
                "request": REQ,
            }
        ]
        self._post({"sys_id": SET, "number": "SCTASK0000001"})
        r = self.run_tool(
            action="add_task",
            record_id="RITM0000001",
            short_description="Prep",
            assignment_group="grp_one",
        )
        body = self.writes()[0].kwargs["json"]
        self.assertEqual(body["request_item"], RITM)
        self.assertEqual(body["request"], REQ)
        self.assertEqual(body["assignment_group"], "grp_one")
        self.assertTrue(r["wired"])

    def test_dry_run_makes_no_write(self):
        self.tables["sc_req_item"] = [self._ritm()]
        for kw in (
            {"action": "add_task", "short_description": "Prep"},
            {"action": "update", "work_notes": "hi"},
            {"action": "set_state", "state": "Pending"},
        ):
            self.run_tool(record_id="RITM0000001", dry_run=True, **kw)
        self.auth.make_request.assert_not_called()

    def test_update_writes_only_given_fields(self):
        self.tables["sc_task"] = [{"sys_id": SET, "number": "SCTASK0000001"}]
        self._post({})
        r = self.run_tool(action="update", record_id="SCTASK0000001", work_notes="done")
        self.assertTrue(r["success"])
        self.assertEqual(self.writes()[0].kwargs["json"], {"work_notes": "done"})

    def test_get_not_found(self):
        self.tables["sc_req_item"] = []
        r = self.run_tool(action="get", record_id="RITM0009999")
        self.assertEqual(r["error"], "NOT_FOUND")


def test_param_validation():
    with pytest.raises(ValidationError):
        ManageRequestItemParams(action="order")
    with pytest.raises(ValidationError):
        ManageRequestItemParams(action="update", record_id="RITM1")
    with pytest.raises(ValidationError):
        ManageRequestItemParams(action="add_task", record_id="RITM1")


class TestOrderRecordProducer(Base):
    TARGET = "dddd4444eeee5555ffff6666aaaa2222"

    def setUp(self):
        super().setUp()
        self.tables["item_option_new"] = [_var("short_description", "true")]
        self.tables["io_set_item"] = []
        self.tables["sc_cat_item_producer"] = [
            {"sys_id": ITEM, "table_name": "my_table", "sys_class_name": "sc_cat_item_producer"}
        ]

    def test_dry_run_routes_to_submit_producer_without_post(self):
        r = self.run_tool(
            action="order", item_id=ITEM, dry_run=True, variables={"short_description": "x"}
        )
        self.assertEqual(r["route"], "submit_producer")
        self.assertEqual(r["payload"], {"variables": {"short_description": "x"}})
        self.auth.make_request.assert_not_called()

    def test_submit_then_reread_confirms(self):
        self._post({"sys_id": self.TARGET, "number": "REC1", "table": "my_table"})
        self.tables["my_table"] = [{"sys_id": self.TARGET, "number": "REC1"}]
        r = self.run_tool(action="order", item_id=ITEM, variables={"short_description": "x"})
        self.assertTrue(r["applied"])
        self.assertEqual((r["table"], r["number"], r["sys_id"]), ("my_table", "REC1", self.TARGET))
        url = self.writes()[0].args[1]
        self.assertTrue(url.endswith(f"/items/{ITEM}/submit_producer"))
        self.assertEqual(self.writes()[0].kwargs["json"], {"variables": {"short_description": "x"}})

    def test_missing_table_in_response_falls_back_to_producer_table(self):
        self._post({"sys_id": self.TARGET})
        self.tables["my_table"] = [{"sys_id": self.TARGET, "number": "REC2"}]
        r = self.run_tool(action="order", item_id=ITEM, variables={"short_description": "x"})
        self.assertTrue(r["applied"])
        self.assertEqual(r["table"], "my_table")

    def test_no_sys_id_in_response_is_not_success(self):
        self._post({"number": "REC3"})
        r = self.run_tool(action="order", item_id=ITEM, variables={"short_description": "x"})
        self.assertFalse(r["success"])
        self.assertFalse(r["applied"])

    def test_record_not_found_on_reread_is_unconfirmed(self):
        self._post({"sys_id": self.TARGET, "table": "my_table"})
        self.tables["my_table"] = []
        r = self.run_tool(action="order", item_id=ITEM, variables={"short_description": "x"})
        self.assertFalse(r["applied"])

    def test_unreadable_class_check_refuses(self):
        def boom(kw):
            raise RuntimeError("403")

        self.tables["sc_cat_item_producer"] = boom
        r = self.run_tool(action="order", item_id=ITEM, variables={"short_description": "x"})
        self.assertEqual(r["error"], "ITEM_CLASS_UNVERIFIED")
        self.auth.make_request.assert_not_called()

    def test_variables_still_validated(self):
        r = self.run_tool(action="order", item_id=ITEM, variables={"typo": "x"})
        self.assertEqual(r["error"], "UNKNOWN_VARIABLES")


class TestOrderMultiRowSet(Base):
    """A multi-row set is ONE variable (a JSON array of rows), not its columns."""

    def setUp(self):
        super().setUp()
        self.tables["item_option_new"] = lambda kw: (
            [
                {**_var("asset", "true"), "variable_set": SET},
                {**_var("quantity", "true", default="0"), "variable_set": SET},
            ]
            if "variable_setIN" in kw["query"]
            else [_var("note")]
        )
        self.tables["io_set_item"] = [{"variable_set": SET}]
        self.tables["item_option_new_set"] = [
            {"sys_id": SET, "internal_name": "rows_set", "type": "one_to_many"}
        ]

    def order(self, variables):
        return self.run_tool(action="order", item_id=ITEM, dry_run=True, variables=variables)

    def test_rows_are_sent_as_one_json_string(self):
        r = self.order({"rows_set": [{"asset": "a1", "quantity": 1}]})
        self.assertTrue(r["dry_run"])
        self.assertEqual(
            r["payload"]["variables"], {"rows_set": '[{"asset": "a1", "quantity": "1"}]'}
        )

    def test_json_string_is_accepted(self):
        r = self.order({"rows_set": '[{"asset": "a1"}]'})
        self.assertEqual(r["payload"]["variables"]["rows_set"], '[{"asset": "a1"}]')

    def test_columns_at_top_level_are_refused_with_a_pointer(self):
        r = self.order({"asset": "a1"})
        self.assertEqual(r["error"], "UNKNOWN_VARIABLES")
        self.assertIn("asset -> rows_set", r["message"])

    def test_columns_are_not_demanded_at_top_level(self):
        r = self.order({})
        self.assertTrue(r["dry_run"])

    def test_row_missing_a_mandatory_column(self):
        r = self.order({"rows_set": [{"quantity": "1"}]})
        self.assertEqual(r["error"], "MISSING_MANDATORY")
        self.assertEqual(r["missing"], ["asset"])

    def test_row_with_an_unknown_column(self):
        r = self.order({"rows_set": [{"asset": "a1", "typo": "x"}]})
        self.assertEqual(r["error"], "UNKNOWN_VARIABLES")
        self.assertEqual(r["unknown"], ["typo"])

    def test_not_a_list(self):
        r = self.order({"rows_set": {"asset": "a1"}})
        self.assertEqual(r["error"], "BAD_MULTI_ROW_SET")

    def test_unreadable_set_record_refuses(self):
        self.tables["item_option_new_set"] = []
        r = self.order({"rows_set": [{"asset": "a1"}]})
        self.assertEqual(r["error"], "VARIABLES_UNVERIFIED")
        self.auth.make_request.assert_not_called()
