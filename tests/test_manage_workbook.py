"""manage_workbook: generic Excel legwork, caps named, forms never overwritten.

Workbooks under test are built through the tool's own writer, not hand-made
fixtures — a fixture drifts from its producer, a round-trip cannot.
"""

import datetime
from types import SimpleNamespace

import pytest

openpyxl = pytest.importorskip("openpyxl")

from servicenow_mcp.tools.workbook_tools import ManageWorkbookParams, manage_workbook  # noqa: E402
from servicenow_mcp.utils import workbook_io  # noqa: E402

CFG = SimpleNamespace()
AUTH = SimpleNamespace()


def call(**kw):
    return manage_workbook(CFG, AUTH, ManageWorkbookParams(**kw))


@pytest.fixture
def tracker(tmp_path):
    """A small tracking workbook, produced by the real writer."""
    path = str(tmp_path / "tracker.xlsx")
    result = call(
        action="write",
        output_file=path,
        spec={
            "sheets": [
                {
                    "title": "Hypercare",
                    "header_row": 1,
                    "widths": [6, 12, 30, 10],
                    "rows": [
                        ["No", "접수일", "요청내용", "PIC"],
                        [383, "2026-07-15", "리비전 버튼이 안 보임", "alice"],
                        [407, "2026-07-16", "Revision 금액 오류", "bob"],
                        [422, "2026-07-18", "SM 권한 요청", "alice"],
                    ],
                }
            ]
        },
    )
    assert result["success"] is True
    return path


class TestValidation:
    @pytest.mark.parametrize(
        "kw",
        [
            {"action": "read"},  # no path
            {"action": "find", "path": "x.xlsx"},  # no query
            {"action": "write", "output_file": "y.xlsx"},  # no spec
            {"action": "write", "spec": {"sheets": [{}]}},  # no output
            {"action": "fill", "path": "x.xlsx", "output_file": "y.xlsx"},  # nothing to fill
        ],
    )
    def test_missing_required_fields_fail_at_the_schema(self, kw):
        with pytest.raises(ValueError):
            ManageWorkbookParams(**kw)

    def test_narrowing_map_names_only_real_fields(self):
        fields = set(ManageWorkbookParams.model_fields)
        for action, names in ManageWorkbookParams._FIELDS_BY_ACTION.items():
            assert names <= fields, f"{action} narrows to unknown fields {names - fields}"


class TestRead:
    def test_sheets_lists_names_and_sizes(self, tracker):
        result = call(action="sheets", path=tracker)
        assert result["sheets"] == [{"name": "Hypercare", "rows": 4, "cols": 4}]

    def test_read_caps_and_names_the_truncation(self, tracker):
        result = call(action="read", path=tracker, limit=2)
        assert len(result["rows"]) == 2
        assert result["row_numbers"] == [1, 2]
        # A partial read must say it is partial, and say how to continue.
        assert "min_row=3" in result["truncated"]

    def test_read_from_offset_reaches_the_end_without_a_truncation_claim(self, tracker):
        result = call(action="read", path=tracker, min_row=3)
        assert result["row_numbers"] == [3, 4]
        assert "truncated" not in result

    def test_columns_projection(self, tracker):
        result = call(action="read", path=tracker, columns="A,C", limit=2)
        assert result["rows"][1] == [383, "리비전 버튼이 안 보임"]

    def test_unknown_sheet_answers_with_the_real_names(self, tracker):
        result = call(action="read", path=tracker, sheet="없는시트")
        assert result["success"] is False
        assert "Hypercare" in result["error"]

    def test_long_cells_are_truncated_with_a_marker(self, tmp_path):
        path = str(tmp_path / "long.xlsx")
        call(
            action="write",
            output_file=path,
            spec={"sheets": [{"title": "S", "rows": [["x" * 300]]}]},
        )
        result = call(action="read", path=path)
        cell = result["rows"][0][0]
        assert len(cell) < 300 and "…(+100자)" in cell

    def test_dates_come_back_readable(self, tmp_path):
        path = str(tmp_path / "d.xlsx")
        wb = openpyxl.Workbook()
        wb.active.append([datetime.datetime(2026, 7, 15), datetime.datetime(2026, 7, 15, 9, 30)])
        wb.save(path)
        result = call(action="read", path=path)
        assert result["rows"][0] == ["2026-07-15", "2026-07-15 09:30"]


class TestFind:
    def test_regex_across_the_row_text(self, tracker):
        result = call(action="find", path=tracker, query="리비전|revision", columns="A")
        assert result["matches"] == 2
        assert [r[0] for r in result["rows"]] == [383, 407]

    def test_query_scoped_to_one_column(self, tracker):
        result = call(action="find", path=tracker, query="^407$", column="A")
        assert result["matches"] == 1
        assert result["row_numbers"] == [3]

    def test_match_overflow_is_reported_not_silent(self, tracker):
        result = call(action="find", path=tracker, query="alice", limit=1)
        assert result["matches"] == 2
        assert len(result["rows"]) == 1
        assert "truncated" in result

    def test_a_broken_regex_answers_instead_of_raising(self, tracker):
        result = call(action="find", path=tracker, query="[unclosed")
        assert result["success"] is False
        assert "error" in result


class TestWrite:
    def test_house_style_lands_on_the_header(self, tracker):
        ws = openpyxl.load_workbook(tracker).active
        header = ws.cell(1, 1)
        assert header.font.bold is True
        assert header.fill.start_color.rgb.endswith("1F4E79")
        assert ws.cell(2, 1).border.left.style == "thin"

    def test_empty_spec_is_an_error(self, tmp_path):
        result = call(action="write", output_file=str(tmp_path / "e.xlsx"), spec={"sheets": []})
        assert result["success"] is False

    def test_image_embeds_and_missing_image_is_named(self, tmp_path):
        pytest.importorskip("PIL")
        from PIL import Image

        shot = str(tmp_path / "shot.png")
        Image.new("RGB", (900, 400), (10, 20, 30)).save(shot)
        path = str(tmp_path / "img.xlsx")
        result = call(
            action="write",
            output_file=path,
            spec={
                "sheets": [
                    {
                        "title": "증적",
                        "rows": [["케이스", "증적"]],
                        "images": [
                            {"path": shot, "cell": "B2"},
                            {"path": str(tmp_path / "ghost.png"), "cell": "B3"},
                        ],
                    }
                ]
            },
        )
        assert result["embedded_images"] == 1
        assert any("ghost.png" in note for note in result["image_notes"])
        # The embedded copy is resized — the workbook never carries full pixels.
        assert (tmp_path / "shot.thumb.png").exists()


class TestFill:
    def test_fill_writes_a_copy_and_never_the_form(self, tracker, tmp_path):
        out = str(tmp_path / "filled.xlsx")
        result = call(
            action="fill",
            path=tracker,
            output_file=out,
            cells={"D2": "확인 완료"},
            rows_at={"start_row": 6, "rows": [[500, "2026-08-14", "신규", "alice"]]},
        )
        assert result["success"] is True
        assert result["cells_written"] == 1 and result["rows_written"] == 1
        filled = openpyxl.load_workbook(out).active
        assert filled["D2"].value == "확인 완료"
        assert filled.cell(6, 1).value == 500
        # The form itself is untouched.
        original = openpyxl.load_workbook(tracker).active
        assert original["D2"].value == "alice"

    def test_filling_the_form_onto_itself_is_refused(self, tracker):
        result = call(action="fill", path=tracker, output_file=tracker, cells={"A1": "x"})
        assert result["success"] is False
        assert "input" in result["error"]

    def test_missing_template_is_a_clear_error(self, tmp_path):
        result = call(
            action="fill",
            path=str(tmp_path / "nope.xlsx"),
            output_file=str(tmp_path / "out.xlsx"),
            cells={"A1": "x"},
        )
        assert result["success"] is False
        assert "not found" in result["error"]


class TestDependencyDegradation:
    def test_missing_openpyxl_answers_with_the_install_hint(self, monkeypatch, tracker):
        def _raise():
            raise workbook_io.OpenpyxlUnavailable("openpyxl is not installed. …")

        monkeypatch.setattr(workbook_io, "require_openpyxl", _raise)
        result = call(action="sheets", path=tracker)
        assert result["success"] is False
        assert "openpyxl" in result["error"]
