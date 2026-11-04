"""manage_asset: every value is checked against the instance before a write.

The Table API stores an unknown column by dropping it, a non-choice status as
typed and a dangling reference as-is, all with a 200. So each test that expects
a refusal also asserts that nothing was sent.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from servicenow_mcp.services import asset as svc
from servicenow_mcp.tools.asset_tools import ManageAssetParams, manage_asset

MODEL = "aaaa1111bbbb2222cccc3333dddd0001"
CATEGORY = "aaaa1111bbbb2222cccc3333dddd0002"
ROOM_A = "aaaa1111bbbb2222cccc3333dddd0003"
ROOM_B = "aaaa1111bbbb2222cccc3333dddd0004"
ASSET = "aaaa1111bbbb2222cccc3333dddd0005"
USER = "aaaa1111bbbb2222cccc3333dddd0006"

COLUMNS = {
    "model",
    "model_category",
    "asset_tag",
    "serial_number",
    "install_status",
    "substatus",
    "stockroom",
    "assigned_to",
    "location",
}
ORDER_COLUMNS = {"from_stockroom", "to_stockroom", "requested_date"}
LINE_COLUMNS = {
    "transfer_order",
    "model",
    "asset",
    "quantity_requested",
    "from_stockroom",
    "to_stockroom",
}

CHOICES = {
    "install_status": [
        {"value": "1", "label": "In use"},
        {"value": "6", "label": "In stock"},
    ],
    "substatus": [
        {"value": "available", "label": "Available", "dependent_value": "6"},
        {"value": "reserved", "label": "Reserved", "dependent_value": "6"},
    ],
}


def _asset_row(**over):
    row = {
        "sys_id": ASSET,
        "sys_class_name": "alm_hardware",
        "asset_tag": "P1000",
        "model": MODEL,
        "install_status": "6",
        "stockroom": ROOM_A,
    }
    row.update(over)
    return row


class Instance:
    """A scripted instance: table → rows, plus the schema reads."""

    def __init__(self, tables=None, columns=None, ancestry=None):
        self.tables = {
            "cmdb_model": [{"sys_id": MODEL, "cmdb_model_category": CATEGORY}],
            "cmdb_model_category": [{"sys_id": CATEGORY}],
            "alm_stockroom": [{"sys_id": ROOM_A}, {"sys_id": ROOM_B}],
            "sys_user": [{"sys_id": USER}],
            "alm_asset": [_asset_row()],
        }
        self.tables.update(tables or {})
        self.columns = {
            "alm_hardware": COLUMNS,
            "alm_asset": COLUMNS,
            "alm_transfer_order": ORDER_COLUMNS,
            "alm_transfer_order_line": LINE_COLUMNS,
        }
        self.columns.update(columns or {})
        self.ancestry = ancestry or {"alm_hardware": ["alm_hardware", "alm_asset"]}

    def query(self, config, auth_manager, *, table, query, **kw):
        rows = self.tables.get(table, [])
        if query.startswith("sys_id="):
            wanted = query.split("=", 1)[1]
            rows = [r for r in rows if svc._ref(r.get("sys_id")) == wanted]
        elif query.startswith("asset_tag="):
            wanted = query.split("=", 1)[1].split("^", 1)[0]
            rows = [r for r in rows if wanted in (r.get("asset_tag"), r.get("serial_number"))]
        return rows, None

    def __enter__(self):
        self._patches = [
            patch("servicenow_mcp.services.asset.sn_query_page", side_effect=self.query),
            patch(
                "servicenow_mcp.services.asset.table_columns",
                side_effect=lambda c, a, t: self.columns.get(t),
            ),
            patch(
                "servicenow_mcp.services.asset.table_ancestry",
                side_effect=lambda c, a, t: self.ancestry.get(t),
            ),
            patch(
                "servicenow_mcp.services.choices._choice_rows",
                side_effect=lambda c, a, t, e: CHOICES.get(e, []),
            ),
            patch("servicenow_mcp.services.asset.invalidate_query_cache"),
        ]
        for p in self._patches:
            p.start()
        return self

    def __exit__(self, *exc):
        for p in reversed(self._patches):
            p.stop()


def _auth(*results):
    auth = MagicMock()
    responses = []
    for result in results:
        response = MagicMock()
        response.json.return_value = {"result": result}
        responses.append(response)
    auth.make_request.side_effect = responses
    return auth


def _sent(auth):
    return [
        (c.args[0], c.args[1].rsplit("/table/", 1)[1], c.kwargs["json"])
        for c in auth.make_request.call_args_list
    ]


# ---------------------------------------------------------------- get


class TestGet:
    def test_by_tag(self, mock_config):
        with Instance():
            result = svc.get(mock_config, MagicMock(), asset_id="P1000")
        assert result["success"] is True and result["asset"]["sys_id"] == ASSET

    def test_display_values_are_flattened(self, mock_config):
        row = {
            "sys_id": {"value": ASSET, "display_value": ASSET},
            "install_status": {"value": "6", "display_value": "In stock"},
        }
        with Instance(tables={"alm_asset": [row]}):
            result = svc.get(mock_config, MagicMock(), asset_id=ASSET)
        assert result["asset"]["install_status"] == "In stock (6)"

    def test_not_found(self, mock_config):
        with Instance():
            result = svc.get(mock_config, MagicMock(), asset_id="NOPE")
        assert result["error"] == "ASSET_NOT_FOUND"

    def test_tag_and_serial_clash_is_ambiguous(self, mock_config):
        rows = [_asset_row(), _asset_row(sys_id="x", asset_tag="Q", serial_number="P1000")]
        with Instance(tables={"alm_asset": rows}):
            result = svc.get(mock_config, MagicMock(), asset_id="P1000")
        assert result["error"] == "ASSET_AMBIGUOUS" and len(result["candidates"]) == 2

    def test_unreadable_is_not_not_found(self, mock_config):
        with patch("servicenow_mcp.services.asset.sn_query_page", side_effect=RuntimeError("403")):
            result = svc.get(mock_config, MagicMock(), asset_id="P1000")
        assert result["error"] == "ASSET_UNREADABLE"


# ---------------------------------------------------------------- create


class TestCreate:
    def test_category_is_derived_and_status_resolved(self, mock_config):
        auth = _auth(
            {
                "sys_id": "new",
                "asset_tag": "P2000",
                "install_status": "6",
                "model": MODEL,
                "model_category": CATEGORY,
            }
        )
        with Instance():
            result = svc.create(
                mock_config, auth, model=MODEL, asset_tag="P2000", install_status="In stock"
            )
        assert result["success"] is True and result["table"] == "alm_hardware"
        method, table, body = _sent(auth)[0]
        assert (method, table) == ("POST", "alm_hardware")
        assert body["model_category"] == CATEGORY and body["install_status"] == "6"
        assert "server_changed" not in result

    def test_a_field_the_server_rewrote_is_reported(self, mock_config):
        auth = _auth(
            {"sys_id": "new", "install_status": "1", "model": MODEL, "model_category": CATEGORY}
        )
        with Instance():
            result = svc.create(mock_config, auth, model=MODEL, install_status="6")
        assert result["server_changed"] == {"install_status": {"sent": "6", "stored": "1"}}

    def test_not_an_asset_class(self, mock_config):
        auth = _auth()
        with Instance(ancestry={"cmdb_ci": ["cmdb_ci"]}):
            result = svc.create(mock_config, auth, model=MODEL, asset_class="cmdb_ci")
        assert result["error"] == "NOT_AN_ASSET_CLASS"
        auth.make_request.assert_not_called()

    def test_unreadable_hierarchy_refuses(self, mock_config):
        auth = _auth()
        with Instance(ancestry={"x": None}):
            result = svc.create(mock_config, auth, model=MODEL, asset_class="x")
        assert result["error"] == "SCHEMA_UNVERIFIED"
        auth.make_request.assert_not_called()

    def test_missing_model(self, mock_config):
        auth = _auth()
        with Instance(tables={"cmdb_model": []}):
            result = svc.create(mock_config, auth, model=MODEL)
        assert result["error"] == "REFERENCE_NOT_FOUND"
        auth.make_request.assert_not_called()

    def test_model_with_several_categories_needs_one_named(self, mock_config):
        model = {"sys_id": MODEL, "cmdb_model_category": f"{CATEGORY},other"}
        auth = _auth()
        with Instance(tables={"cmdb_model": [model]}):
            result = svc.create(mock_config, auth, model=MODEL)
        assert result["error"] == "MODEL_CATEGORY_REQUIRED"
        auth.make_request.assert_not_called()

    def test_category_not_on_the_model(self, mock_config):
        auth = _auth()
        with Instance():
            result = svc.create(mock_config, auth, model=MODEL, model_category="other")
        assert result["error"] == "MODEL_CATEGORY_MISMATCH"
        auth.make_request.assert_not_called()

    def test_unknown_column(self, mock_config):
        auth = _auth()
        with Instance(columns={"alm_hardware": COLUMNS - {"serial_number"}}):
            result = svc.create(mock_config, auth, model=MODEL, serial_number="S1")
        assert result["error"] == "UNKNOWN_COLUMN" and "serial_number" in result["message"]
        auth.make_request.assert_not_called()

    def test_unreadable_columns(self, mock_config):
        auth = _auth()
        with Instance(columns={"alm_hardware": None}):
            result = svc.create(mock_config, auth, model=MODEL)
        assert result["error"] == "SCHEMA_UNVERIFIED"
        auth.make_request.assert_not_called()

    def test_bad_status(self, mock_config):
        auth = _auth()
        with Instance():
            result = svc.create(mock_config, auth, model=MODEL, install_status="Lost-ish")
        assert result["error"] == "UNKNOWN_CHOICE"
        auth.make_request.assert_not_called()

    def test_substatus_of_another_status(self, mock_config):
        auth = _auth()
        with Instance():
            result = svc.create(
                mock_config, auth, model=MODEL, install_status="In use", substatus="reserved"
            )
        assert result["error"] in ("UNKNOWN_CHOICE", "CHOICE_UNVERIFIED")
        auth.make_request.assert_not_called()

    def test_substatus_alone_needs_a_status(self, mock_config):
        auth = _auth()
        with Instance():
            result = svc.create(mock_config, auth, model=MODEL, substatus="reserved")
        assert result["error"] == "SUBSTATUS_NEEDS_STATUS"
        auth.make_request.assert_not_called()

    def test_dangling_user(self, mock_config):
        auth = _auth()
        with Instance(tables={"sys_user": []}):
            result = svc.create(mock_config, auth, model=MODEL, assigned_to=USER)
        assert result["error"] == "REFERENCE_NOT_FOUND" and "assigned_to" in result["message"]
        auth.make_request.assert_not_called()


# ---------------------------------------------------------------- update


class TestUpdate:
    def test_substatus_resolves_under_the_current_status(self, mock_config):
        auth = _auth({"sys_id": ASSET, "substatus": "reserved"})
        with Instance():
            result = svc.update(mock_config, auth, asset_id="P1000", substatus="Reserved")
        assert result["success"] is True
        method, table, body = _sent(auth)[0]
        assert (method, table) == ("PATCH", f"alm_hardware/{ASSET}")
        assert body == {"substatus": "reserved"}

    def test_dry_run_is_a_diff_and_writes_nothing(self, mock_config):
        auth = _auth()
        with (
            Instance(),
            patch(
                "servicenow_mcp.services.asset.build_update_preview",
                return_value={"dry_run": True, "proposed_changes": {}},
            ) as preview,
        ):
            result = svc.update(
                mock_config, auth, asset_id="P1000", install_status="In use", dry_run=True
            )
        assert result["dry_run"] is True
        assert preview.call_args.kwargs["proposed"] == {"install_status": "1"}
        auth.make_request.assert_not_called()

    def test_nothing_to_update(self, mock_config):
        with Instance():
            result = svc.update(mock_config, _auth(), asset_id="P1000")
        assert result["error"] == "NOTHING_TO_UPDATE"

    def test_unknown_asset(self, mock_config):
        auth = _auth()
        with Instance():
            result = svc.update(mock_config, auth, asset_id="NOPE", asset_tag="X")
        assert result["error"] == "ASSET_NOT_FOUND"
        auth.make_request.assert_not_called()


# ---------------------------------------------------------------- transfer


class TestTransfer:
    def test_one_line_per_asset(self, mock_config):
        auth = _auth({"sys_id": "to1", "number": "TO0001", "stage": "draft"}, {"sys_id": "l1"})
        with Instance():
            result = svc.transfer(
                mock_config, auth, from_stockroom=ROOM_A, to_stockroom=ROOM_B, asset_ids=["P1000"]
            )
        assert result["success"] is True and result["lines_created"] == 1
        (m1, t1, order), (m2, t2, line) = _sent(auth)
        assert (t1, t2) == ("alm_transfer_order", "alm_transfer_order_line")
        assert order["from_stockroom"] == ROOM_A and order["to_stockroom"] == ROOM_B
        assert line["transfer_order"] == "to1" and line["asset"] == ASSET

    def test_an_asset_outside_the_source_stockroom_writes_nothing(self, mock_config):
        auth = _auth()
        with Instance(tables={"alm_asset": [_asset_row(stockroom=ROOM_B)]}):
            result = svc.transfer(
                mock_config, auth, from_stockroom=ROOM_A, to_stockroom=ROOM_B, asset_ids=["P1000"]
            )
        assert result["error"] == "NOT_IN_SOURCE_STOCKROOM"
        auth.make_request.assert_not_called()

    def test_dry_run_returns_the_plan(self, mock_config):
        auth = _auth()
        with Instance():
            result = svc.transfer(
                mock_config,
                auth,
                from_stockroom=ROOM_A,
                to_stockroom=ROOM_B,
                model=MODEL,
                quantity=3,
                dry_run=True,
            )
        assert result["dry_run"] is True
        assert result["would_create"]["alm_transfer_order_line"][0]["quantity_requested"] == 3
        auth.make_request.assert_not_called()

    def test_a_failed_line_reports_the_order_it_left_behind(self, mock_config):
        auth = MagicMock()
        ok = MagicMock()
        ok.json.return_value = {"result": {"sys_id": "to1", "number": "TO0001"}}
        auth.make_request.side_effect = [ok, RuntimeError("500")]
        with Instance():
            result = svc.transfer(
                mock_config, auth, from_stockroom=ROOM_A, to_stockroom=ROOM_B, asset_ids=["P1000"]
            )
        assert result["error"] == "PARTIAL_TRANSFER"
        assert result["transfer_order_id"] == "to1" and "TO0001" in result["message"]

    def test_same_stockroom(self, mock_config):
        result = svc.transfer(mock_config, _auth(), from_stockroom=ROOM_A, to_stockroom=ROOM_A)
        assert result["error"] == "SAME_STOCKROOM"

    def test_unknown_stockroom(self, mock_config):
        auth = _auth()
        with Instance(tables={"alm_stockroom": [{"sys_id": ROOM_A}]}):
            result = svc.transfer(
                mock_config,
                auth,
                from_stockroom=ROOM_A,
                to_stockroom=ROOM_B,
                model=MODEL,
                quantity=1,
            )
        assert result["error"] == "REFERENCE_NOT_FOUND"
        auth.make_request.assert_not_called()

    def test_nothing_to_transfer(self, mock_config):
        with Instance():
            result = svc.transfer(
                mock_config, _auth(), from_stockroom=ROOM_A, to_stockroom=ROOM_B, model=MODEL
            )
        assert result["error"] == "NOTHING_TO_TRANSFER"

    def test_line_columns_are_checked(self, mock_config):
        auth = _auth()
        with Instance(columns={"alm_transfer_order_line": LINE_COLUMNS - {"asset"}}):
            result = svc.transfer(
                mock_config, auth, from_stockroom=ROOM_A, to_stockroom=ROOM_B, asset_ids=["P1000"]
            )
        assert result["error"] == "UNKNOWN_COLUMN"
        auth.make_request.assert_not_called()


# ---------------------------------------------------------------- tool


class TestTool:
    @pytest.mark.parametrize(
        "kwargs,match",
        [
            ({"action": "get"}, "asset_id"),
            ({"action": "update"}, "asset_id"),
            ({"action": "create"}, "model"),
            ({"action": "transfer", "stockroom": ROOM_A}, "to_stockroom"),
        ],
    )
    def test_required_per_action(self, kwargs, match):
        with pytest.raises(ValueError, match=match):
            ManageAssetParams(**kwargs)

    def test_transfer_routes_stockroom_as_the_source(self, mock_config):
        with patch("servicenow_mcp.tools.asset_tools.asset_service.transfer") as transfer:
            manage_asset(
                mock_config,
                MagicMock(),
                ManageAssetParams(
                    action="transfer", stockroom=ROOM_A, to_stockroom=ROOM_B, asset_ids=["P1"]
                ),
            )
        kw = transfer.call_args.kwargs
        assert kw["from_stockroom"] == ROOM_A and kw["to_stockroom"] == ROOM_B

    def test_every_declared_field_belongs_to_an_action(self):
        declared = set(ManageAssetParams.model_fields) - {"action"}
        mapped = set().union(*ManageAssetParams._FIELDS_BY_ACTION.values())
        assert declared == mapped
