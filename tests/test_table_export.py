"""manage_workbook write with a ``source``: the server reads rows into the file,
the caller gets counts and a column profile — never the rows themselves."""

import json
from typing import Dict, List
from unittest.mock import MagicMock

import pytest

from servicenow_mcp.services import data_update as du
from servicenow_mcp.services import table_export as tx
from servicenow_mcp.tools.workbook_tools import ManageWorkbookParams, manage_workbook
from servicenow_mcp.utils.config import ServerConfig

openpyxl = pytest.importorskip("openpyxl")


def _sid(i: int) -> str:
    return f"aaaa1111bbbb2222cccc3333{i:08x}"


class Server:
    """Rows of one table. Like ServiceNow: an unknown field's condition is DROPPED
    and an unknown field in ``fields`` is simply absent."""

    def __init__(self, n: int = 2500):
        self.rows: List[Dict[str, str]] = [
            {
                "sys_id": _sid(i),
                "number": f"ORD{i:05d}",
                "state": "Open" if i % 3 else "Closed",
                "region": "" if i % 10 == 0 else ("east" if i % 2 else "west"),
            }
            for i in range(n)
        ]
        self.columns = {"sys_id", "number", "state", "region"}
        self.hidden = 0
        self.report_count = True
        self.reads = 0

    def _match(self, row, query):
        for cond in filter(None, (query or "").split("^")):
            f, _, v = cond.partition("=")
            if f not in row:
                continue  # dropped
            if row[f] != v:
                return False
        return True

    def query_page(self, config, auth, *, table, query, fields, limit, offset, **kw):
        self.reads += 1
        rows = [r for r in self.rows if self._match(r, query)]
        total = len(rows) if self.report_count else None
        if fields != "sys_id" and self.hidden:
            rows = rows[self.hidden :]
        want = fields.split(",")
        page = [{f: r[f] for f in want if f in r} for r in rows[offset : offset + limit]]
        return page, total


@pytest.fixture
def server(monkeypatch):
    s = Server()
    for mod in (du, tx):
        monkeypatch.setattr(mod, "sn_query_page", s.query_page)
        monkeypatch.setattr(mod, "table_columns", lambda c, a, t: s.columns)
    monkeypatch.setattr(
        du, "query_field_names", lambda q: [p.partition("=")[0] for p in q.split("^") if p]
    )
    return s


@pytest.fixture
def config():
    return ServerConfig(
        instance_url="https://test.service-now.com",
        auth={"type": "basic", "basic": {"username": "admin", "password": "password"}},
    )


def write(config, tmp_path, *sheets):
    out = tmp_path / "out.xlsx"
    r = manage_workbook(
        config,
        MagicMock(),
        ManageWorkbookParams(action="write", spec={"sheets": list(sheets)}, output_file=str(out)),
    )
    return r, out


def test_rows_go_to_the_file_and_only_counts_come_back(server, config, tmp_path):
    r, out = write(
        config,
        tmp_path,
        {
            "title": "Orders",
            "source": {
                "table": "x_myapp_order",
                "query": "state=Open",
                "fields": "number,state,region",
            },
        },
    )
    assert r["success"]
    proof = r["exported"][0]
    assert proof["matched"] == proof["rows"] == 1666 and proof["complete"]
    ws = openpyxl.load_workbook(out)["Orders"]
    assert ws.max_row == 1667 and [c.value for c in ws[1]] == ["number", "state", "region"]
    numbers = {ws.cell(i, 1).value for i in range(2, ws.max_row + 1)}
    assert numbers == {r_["number"] for r_ in server.rows if r_["state"] == "Open"}
    assert "ORD00001" not in json.dumps(r)  # no row data in the response


def test_the_profile_answers_first_questions_without_rows(server, config, tmp_path):
    r, _ = write(
        config,
        tmp_path,
        {"title": "All", "source": {"table": "x_myapp_order", "fields": ["state", "region"]}},
    )
    cols = r["exported"][0]["columns"]
    assert cols["state"]["distinct"] == 2 and cols["state"]["top"][0] == ["Open", 1666]
    assert cols["region"]["empty"] == 250


def test_a_unique_column_lists_no_values(server, config, tmp_path):
    r, _ = write(
        config, tmp_path, {"title": "All", "source": {"table": "x_myapp_order", "fields": "number"}}
    )
    col = r["exported"][0]["columns"]["number"]
    assert col == {"empty": 0, "distinct": 2500, "all_distinct": True}


def test_an_unknown_query_field_is_refused_not_exported_as_the_whole_table(
    server, config, tmp_path
):
    r, out = write(
        config,
        tmp_path,
        {
            "title": "S",
            "source": {"table": "x_myapp_order", "query": "stat=Open", "fields": "number"},
        },
    )
    assert r["success"] is False and r["error"] == "UNKNOWN_QUERY_FIELDS"
    assert not out.exists()


def test_an_unknown_export_field_is_refused_not_written_as_an_empty_column(
    server, config, tmp_path
):
    r, out = write(
        config,
        tmp_path,
        {"title": "S", "source": {"table": "x_myapp_order", "fields": "number,regoin"}},
    )
    assert r["error"] == "UNKNOWN_FIELD" and "region" in r["did_you_mean"]
    assert not out.exists()


def test_over_cap_is_refused_not_cut(server, config, tmp_path):
    r, out = write(
        config,
        tmp_path,
        {"title": "S", "source": {"table": "x_myapp_order", "fields": "number", "max_rows": 100}},
    )
    assert r["error"] == "OVER_CAP" and r["matched"] == 2500
    assert not out.exists()


def test_rows_the_server_counted_but_did_not_return_mark_the_sheet_incomplete(
    server, config, tmp_path
):
    server.hidden = 7
    r, _ = write(
        config, tmp_path, {"title": "S", "source": {"table": "x_myapp_order", "fields": "number"}}
    )
    proof = r["exported"][0]
    assert proof["complete"] is False and proof["rows"] == 2493 and "incomplete_note" in proof


def test_an_unreported_count_writes_no_file(server, config, tmp_path):
    server.report_count = False
    r, out = write(
        config, tmp_path, {"title": "S", "source": {"table": "x_myapp_order", "fields": "number"}}
    )
    assert r["error"] == "COUNT_UNVERIFIED" and not out.exists()


def test_one_refused_sheet_means_no_file_at_all(server, config, tmp_path):
    r, out = write(
        config,
        tmp_path,
        {"title": "Good", "source": {"table": "x_myapp_order", "fields": "number"}},
        {"title": "Bad", "source": {"table": "x_myapp_order", "fields": "nope"}},
    )
    assert r["error"] == "UNKNOWN_FIELD" and r["sheet"] == "Bad" and not out.exists()


def test_inline_rows_still_work_beside_a_source(server, config, tmp_path):
    r, out = write(
        config,
        tmp_path,
        {"title": "Cover", "rows": [["Report"], ["generated"]]},
        {
            "title": "Data",
            "source": {"table": "x_myapp_order", "query": "region=east", "fields": "number"},
        },
    )
    assert r["success"] and len(r["exported"]) == 1
    assert openpyxl.load_workbook(out)["Cover"]["A1"].value == "Report"


def test_a_dotwalk_typo_in_an_export_field_says_empty_column(server, config, tmp_path, monkeypatch):
    monkeypatch.setattr(
        tx,
        "_check_dotwalk",
        lambda c, a, t, f: {
            "success": False,
            "error": "UNKNOWN_QUERY_FIELDS",
            "message": "sys_user has no column 'nmae' (in caller_id.nmae); the server would drop that condition",
        },
    )
    r, out = write(
        config,
        tmp_path,
        {"title": "S", "source": {"table": "x_myapp_order", "fields": "number,caller_id.nmae"}},
    )
    assert (
        r["error"] == "UNKNOWN_FIELD"
        and "empty column" in r["message"]
        and "drop" not in r["message"]
    )
    assert not out.exists()
